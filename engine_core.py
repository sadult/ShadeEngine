"""
Shade Engine - core packet-injection backend.

This single module merges what used to be split across:
    main.py, fake_tcp.py, injecter.py, monitor_connection.py,
    utils/network_tools.py, utils/packet_templates.py

It is Windows-only: it depends on the WinDivert driver through `pydivert`.
It is launched in a separate process by the GUI (see shade_engine.py --engine)
and streams its logs to the GUI through stdout/stderr.
"""

import asyncio
import json
import os
import socket
import struct
import sys
import threading
import time
import traceback
from abc import ABC, abstractmethod

APP_VERSION = "1.0.0"


# ==========================================================================
#  Helpers
# ==========================================================================
def get_exe_dir():
    """Directory that holds the running .exe (or this script in dev mode)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def log(msg):
    """Unbuffered print so the GUI console sees logs live."""
    print(msg, flush=True)


def _set_keepalive(sock):
    """Best-effort TCP keepalive tuning (constants differ across platforms)."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except Exception:
        pass
    for opt_name, value in (("TCP_KEEPIDLE", 11), ("TCP_KEEPINTVL", 2), ("TCP_KEEPCNT", 3)):
        opt = getattr(socket, opt_name, None)
        if opt is None:
            continue
        try:
            sock.setsockopt(socket.IPPROTO_TCP, opt, value)
        except Exception:
            pass


# ==========================================================================
#  network_tools
# ==========================================================================
def get_default_interface_ipv4(addr="8.8.8.8") -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((addr, 53))
    except OSError:
        return ""
    else:
        return s.getsockname()[0]
    finally:
        s.close()


def get_default_interface_ipv6(addr="2001:4860:4860::8888") -> str:
    s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    try:
        s.connect((addr, 53))
    except OSError:
        return ""
    else:
        return s.getsockname()[0]
    finally:
        s.close()


# ==========================================================================
#  packet_templates
# ==========================================================================
class ClientHelloMaker:
    tls_ch_template_str = "1603010200010001fc030341d5b549d9cd1adfa7296c8418d157dc7b624c842824ff493b9375bb48d34f2b20bf018bcc90a7c89a230094815ad0c15b736e38c01209d72d282cb5e2105328150024130213031301c02cc030c02bc02fcca9cca8c024c028c023c027009f009e006b006700ff0100018f0000000b00090000066d63692e6972000b000403000102000a00160014001d0017001e0019001801000101010201030104002300000010000e000c02683208687474702f312e310016000000170000000d002a0028040305030603080708080809080a080b080408050806040105010601030303010302040205020602002b00050403040303002d00020101003300260024001d0020435bacc4d05f9d41fef44ab3ad55616c36e0613473e2338770efdaa98693d217001500d5000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    tls_ch_template = bytes.fromhex(tls_ch_template_str)
    template_sni = "mci.ir".encode()
    static1 = tls_ch_template[:11]
    static2 = b"\x20"
    static3 = tls_ch_template[76:120]
    static4 = tls_ch_template[127 + len(template_sni):262 + len(template_sni)]
    static5 = b"\x00\x15"
    ##############
    tls_change_cipher = b"\x14\x03\x03\x00\x01\x01"
    tls_app_data_header = b"\x17\x03\x03"

    @classmethod
    def get_client_hello_with(cls, rnd: bytes, sess_id: bytes, target_sni: bytes,
                              key_share: bytes) -> bytes:  # rnd,sess_id,key_share: 32 bytes
        server_name_ext = struct.pack("!H", len(target_sni) + 5) + struct.pack("!H",
                                                                               len(target_sni) + 3) + b"\x00" + struct.pack(
            "!H", len(target_sni)) + target_sni
        padding_ext = struct.pack("!H", 219 - len(target_sni)) + (b"\x00" * (219 - len(target_sni)))
        return cls.static1 + rnd + cls.static2 + sess_id + cls.static3 + server_name_ext + cls.static4 + key_share + cls.static5 + padding_ext
        # rnd-> [11:43)  sess_id-> [44:76) key_share-> [262+len(target_sni):294+len(target_sni))

    @classmethod
    def parse_client_hello(cls, client_hello_bytes: bytes):
        assert len(client_hello_bytes) == 517
        rnd = client_hello_bytes[11:43]
        sess_id = client_hello_bytes[44:76]
        tls_sni = client_hello_bytes[127:127 + (struct.unpack("!H", client_hello_bytes[125:127])[0])].decode()
        ks_ind = 262 + len(tls_sni)
        key_share = client_hello_bytes[ks_ind:ks_ind + 32]
        assert cls.get_client_hello_with(rnd, sess_id, tls_sni, key_share) == client_hello_bytes
        return rnd, sess_id, tls_sni, key_share

    @classmethod
    def get_client_response_with(cls, app_data1: bytes):
        return cls.tls_change_cipher + cls.tls_app_data_header + struct.pack("!H", len(app_data1)) + app_data1

    @classmethod
    def parse_client_response(cls, client_response_bytes: bytes):
        assert len(client_response_bytes) >= 32
        app_data1 = client_response_bytes[11:]
        assert cls.get_client_response_with(app_data1) == client_response_bytes
        return app_data1


class ServerHelloMaker:
    tls_sh_template_str = "160303007a0200007603035e39ed63ad58140fbd12af1c6a37c879299a39461b308d63cb1dae291c5b69702057d2a640c5ca53fed0f24491baaf96347f12db603fd1babe6bc3ad0b6fbde406130200002e002b0002030400330024001d0020d934ed49a1619be820856c4986e865c5b0e4eb188ebd30193271e8171152eb4e"
    tls_sh_template = bytes.fromhex(tls_sh_template_str)
    static1 = tls_sh_template[:11]
    static2 = b"\x20"
    static3 = tls_sh_template[76:95]
    tls_change_cipher = b"\x14\x03\x03\x00\x01\x01"
    tls_app_data_header = b"\x17\x03\x03"

    @classmethod
    def get_server_hello_with(cls, rnd: bytes, sess_id: bytes, key_share: bytes, app_data1: bytes):
        return cls.static1 + rnd + cls.static2 + sess_id + cls.static3 + key_share + cls.tls_change_cipher + cls.tls_app_data_header + struct.pack(
            "!H", len(app_data1)) + app_data1

    @classmethod
    def parse_server_hello(cls, server_hello_bytes: bytes):
        assert len(server_hello_bytes) >= 159
        rnd = server_hello_bytes[11:43]
        sess_id = server_hello_bytes[44:76]
        key_share = server_hello_bytes[95:127]
        app_data1 = server_hello_bytes[138:]
        assert cls.get_server_hello_with(rnd, sess_id, key_share, app_data1) == server_hello_bytes
        return rnd, sess_id, key_share, app_data1


# ==========================================================================
#  monitor_connection
# ==========================================================================
class MonitorConnection:
    def __init__(self, sock: socket.socket, src_ip, dst_ip, src_port, dst_port):
        self.monitor = True
        self.syn_seq = -1
        self.syn_ack_seq = -1
        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.src_port = src_port
        self.dst_port = dst_port
        self.id = (self.src_ip, self.src_port, self.dst_ip, self.dst_port)
        self.thread_lock = threading.Lock()
        self.sock = sock


# ==========================================================================
#  injecter (pydivert is imported lazily inside the engine process only)
# ==========================================================================
from pydivert import WinDivert, Packet  # noqa: E402  (only imported in engine process)


class TcpInjector(ABC):
    def __init__(self, w_filter: str):
        self.w: WinDivert = WinDivert(w_filter)

    @abstractmethod
    def inject(self, packet: Packet):
        sys.exit("Not implemented")

    def run(self):
        with self.w:
            while True:
                packet = self.w.recv(65575)
                self.inject(packet)


# ==========================================================================
#  fake_tcp
# ==========================================================================
class FakeInjectiveConnection(MonitorConnection):
    def __init__(self, sock: socket.socket, src_ip, dst_ip,
                 src_port, dst_port, fake_data: bytes, bypass_method: str, peer_sock: socket.socket):
        super().__init__(sock, src_ip, dst_ip, src_port, dst_port)
        self.fake_data = fake_data
        self.sch_fake_sent = False
        self.fake_sent = False
        self.t2a_event = asyncio.Event()
        self.t2a_msg = ""
        self.bypass_method = bypass_method
        self.peer_sock = peer_sock
        self.running_loop = asyncio.get_running_loop()


class FakeTcpInjector(TcpInjector):
    def __init__(self, w_filter: str, connections: "dict[tuple, FakeInjectiveConnection]"):
        super().__init__(w_filter)
        self.connections = connections

    def fake_send_thread(self, packet: Packet, connection: FakeInjectiveConnection):
        time.sleep(0.001)
        with connection.thread_lock:
            if not connection.monitor:
                return

            packet.tcp.psh = True
            packet.ip.packet_len = packet.ip.packet_len + len(connection.fake_data)
            packet.tcp.payload = connection.fake_data
            if packet.ipv4:
                packet.ipv4.ident = (packet.ipv4.ident + 1) & 0xffff
            if connection.bypass_method == "wrong_seq":
                packet.tcp.seq_num = (connection.syn_seq + 1 - len(packet.tcp.payload)) & 0xffffffff
                connection.fake_sent = True
                self.w.send(packet, True)
            else:
                sys.exit("not implemented method!")

    def on_unexpected_packet(self, packet: Packet, connection: FakeInjectiveConnection, info_m: str):
        log(info_m)
        connection.sock.close()
        connection.peer_sock.close()
        connection.monitor = False
        connection.t2a_msg = "unexpected_close"
        connection.running_loop.call_soon_threadsafe(connection.t2a_event.set, )
        self.w.send(packet, False)

    def on_inbound_packet(self, packet: Packet, connection: FakeInjectiveConnection):
        if connection.syn_seq == -1:
            self.on_unexpected_packet(packet, connection, "unexpected inbound packet, no syn sent!")
            return
        if packet.tcp.ack and packet.tcp.syn and (not packet.tcp.rst) and (not packet.tcp.fin) and (
                len(packet.tcp.payload) == 0):
            seq_num = packet.tcp.seq_num
            ack_num = packet.tcp.ack_num
            if connection.syn_ack_seq != -1 and connection.syn_ack_seq != seq_num:
                self.on_unexpected_packet(packet, connection,
                                          "unexpected inbound syn-ack packet, seq change! " + str(seq_num) + " " + str(
                                              connection.syn_ack_seq))
                return
            if ack_num != ((connection.syn_seq + 1) & 0xffffffff):
                self.on_unexpected_packet(packet, connection,
                                          "unexpected inbound syn-ack packet, ack not matched! " + str(
                                              ack_num) + " " + str(connection.syn_seq))
                return
            connection.syn_ack_seq = seq_num
            self.w.send(packet, False)
            return
        if packet.tcp.ack and (not packet.tcp.syn) and (not packet.tcp.rst) and (
                not packet.tcp.fin) and (len(packet.tcp.payload) == 0) and connection.fake_sent:
            seq_num = packet.tcp.seq_num
            ack_num = packet.tcp.ack_num
            if connection.syn_ack_seq == -1 or ((connection.syn_ack_seq + 1) & 0xffffffff) != seq_num:
                self.on_unexpected_packet(packet, connection,
                                          "unexpected inbound ack packet, seq not matched! " + str(seq_num) + " " + str(
                                              connection.syn_ack_seq))
                return
            if ack_num != ((connection.syn_seq + 1) & 0xffffffff):
                self.on_unexpected_packet(packet, connection,
                                          "unexpected inbound ack packet, ack not matched! " + str(ack_num) + " " + str(
                                              connection.syn_seq))
                return

            connection.monitor = False
            connection.t2a_msg = "fake_data_ack_recv"
            connection.running_loop.call_soon_threadsafe(connection.t2a_event.set, )
            return
        self.on_unexpected_packet(packet, connection, "unexpected inbound packet")
        return

    def on_outbound_packet(self, packet: Packet, connection: FakeInjectiveConnection):
        if connection.sch_fake_sent:
            self.on_unexpected_packet(packet, connection, "unexpected outbound packet, recv packet after fake sent!")
            return
        if packet.tcp.syn and (not packet.tcp.ack) and (not packet.tcp.rst) and (not packet.tcp.fin) and (
                len(packet.tcp.payload) == 0):
            seq_num = packet.tcp.seq_num
            ack_num = packet.tcp.ack_num
            if ack_num != 0:
                self.on_unexpected_packet(packet, connection, "unexpected outbound syn packet, ack_num is not zero!")
                return
            if connection.syn_seq != -1 and connection.syn_seq != seq_num:
                self.on_unexpected_packet(packet, connection, "unexpected outbound syn packet, seq not matched! " + str(
                    seq_num) + " " + str(connection.syn_seq))
                return
            connection.syn_seq = seq_num
            self.w.send(packet, False)
            return
        if packet.tcp.ack and (not packet.tcp.syn) and (not packet.tcp.rst) and (not packet.tcp.fin) and (
                len(packet.tcp.payload) == 0):
            seq_num = packet.tcp.seq_num
            ack_num = packet.tcp.ack_num
            if connection.syn_seq == -1 or ((connection.syn_seq + 1) & 0xffffffff) != seq_num:
                self.on_unexpected_packet(packet, connection,
                                          "unexpected outbound ack packet, seq not matched! " + str(
                                              seq_num) + " " + str(
                                              connection.syn_seq))
                return
            if connection.syn_ack_seq == -1 or ack_num != ((connection.syn_ack_seq + 1) & 0xffffffff):
                self.on_unexpected_packet(packet, connection,
                                          "unexpected outbound ack packet, ack not matched! " + str(
                                              ack_num) + " " + str(
                                              connection.syn_ack_seq))
                return

            self.w.send(packet, False)
            connection.sch_fake_sent = True
            threading.Thread(target=self.fake_send_thread, args=(packet, connection), daemon=True).start()
            return
        self.on_unexpected_packet(packet, connection, "unexpected outbound packet")
        return

    def inject(self, packet: Packet):
        if packet.is_inbound:
            c_id = (packet.ip.dst_addr, packet.tcp.dst_port, packet.ip.src_addr, packet.tcp.src_port)
            try:
                connection = self.connections[c_id]
            except KeyError:
                self.w.send(packet, False)
            else:
                with connection.thread_lock:
                    if not connection.monitor:
                        self.w.send(packet, False)
                        return
                    self.on_inbound_packet(packet, connection)
        elif packet.is_outbound:
            c_id = (packet.ip.src_addr, packet.tcp.src_port, packet.ip.dst_addr, packet.tcp.dst_port)
            try:
                connection = self.connections[c_id]
            except KeyError:
                self.w.send(packet, False)
            else:
                with connection.thread_lock:
                    if not connection.monitor:
                        self.w.send(packet, False)
                        return
                    self.on_outbound_packet(packet, connection)
        else:
            sys.exit("impossible direction!")


# ==========================================================================
#  Engine runtime (was main.py)
# ==========================================================================
# Runtime state (assigned inside run_engine)
LISTEN_HOST = None
LISTEN_PORT = None
FAKE_SNI = None
CONNECT_IP = None
CONNECT_PORT = None
INTERFACE_IPV4 = None
DATA_MODE = "tls"
BYPASS_METHOD = "wrong_seq"

fake_injective_connections: "dict[tuple, FakeInjectiveConnection]" = {}


async def relay_main_loop(sock_1: socket.socket, sock_2: socket.socket, peer_task: asyncio.Task,
                          first_prefix_data: bytes):
    try:
        loop = asyncio.get_running_loop()
        while True:
            try:
                data = await loop.sock_recv(sock_1, 65575)
                if not data:
                    raise ValueError("eof")
                if first_prefix_data:
                    data = first_prefix_data + data
                    first_prefix_data = b""
                # loop.sock_sendall sends everything or raises; it returns None.
                await loop.sock_sendall(sock_2, data)
            except Exception:
                sock_1.close()
                sock_2.close()
                peer_task.cancel()
                return
    except Exception:
        traceback.print_exc()
        log("relay main loop error!")


async def handle(incoming_sock: socket.socket, incoming_remote_addr):
    try:
        loop = asyncio.get_running_loop()
        if DATA_MODE == "tls":
            fake_data = ClientHelloMaker.get_client_hello_with(os.urandom(32), os.urandom(32), FAKE_SNI,
                                                               os.urandom(32))
        else:
            sys.exit("impossible mode!")
        outgoing_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        outgoing_sock.setblocking(False)
        outgoing_sock.bind((INTERFACE_IPV4, 0))
        _set_keepalive(outgoing_sock)
        src_port = outgoing_sock.getsockname()[1]
        fake_injective_conn = FakeInjectiveConnection(outgoing_sock, INTERFACE_IPV4, CONNECT_IP, src_port, CONNECT_PORT,
                                                      fake_data,
                                                      BYPASS_METHOD, incoming_sock)
        fake_injective_connections[fake_injective_conn.id] = fake_injective_conn
        try:
            await loop.sock_connect(outgoing_sock, (CONNECT_IP, CONNECT_PORT))
        except Exception:
            fake_injective_conn.monitor = False
            fake_injective_connections.pop(fake_injective_conn.id, None)
            outgoing_sock.close()
            incoming_sock.close()
            return

        if BYPASS_METHOD == "wrong_seq":
            try:
                await asyncio.wait_for(fake_injective_conn.t2a_event.wait(), 2)
                if fake_injective_conn.t2a_msg == "unexpected_close":
                    raise ValueError("unexpected close")
                if fake_injective_conn.t2a_msg == "fake_data_ack_recv":
                    pass
                else:
                    sys.exit("impossible t2a msg!")
            except Exception:
                fake_injective_conn.monitor = False
                fake_injective_connections.pop(fake_injective_conn.id, None)
                outgoing_sock.close()
                incoming_sock.close()
                return
        else:
            sys.exit("unknown bypass method!")

        fake_injective_conn.monitor = False
        fake_injective_connections.pop(fake_injective_conn.id, None)

        oti_task = asyncio.create_task(
            relay_main_loop(outgoing_sock, incoming_sock, asyncio.current_task(), b""))
        await relay_main_loop(incoming_sock, outgoing_sock, oti_task, b"")

    except Exception:
        traceback.print_exc()
        log("handle raised an exception (connection dropped)")


async def main():
    mother_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    mother_sock.setblocking(False)
    mother_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    mother_sock.bind((LISTEN_HOST, LISTEN_PORT))
    _set_keepalive(mother_sock)
    mother_sock.listen()
    log(f"Listening on {LISTEN_HOST}:{LISTEN_PORT}  ->  {CONNECT_IP}:{CONNECT_PORT}")
    log(f"Fake SNI: {FAKE_SNI.decode(errors='replace')}  |  Interface: {INTERFACE_IPV4}")
    log("Engine ready. Waiting for connections...")
    loop = asyncio.get_running_loop()
    while True:
        incoming_sock, addr = await loop.sock_accept(mother_sock)
        log(f"New connection accepted from {addr[0]}:{addr[1]}")
        incoming_sock.setblocking(False)
        _set_keepalive(incoming_sock)
        asyncio.create_task(handle(incoming_sock, addr))


def _injector_thread(w_filter: str):
    try:
        injector = FakeTcpInjector(w_filter, fake_injective_connections)
        injector.run()
    except Exception as e:
        log(f"ERROR: WinDivert failed to start: {e!r}")
        log("Make sure the app is running as Administrator and your antivirus "
            "is not blocking the WinDivert driver.")


def run_engine():
    """Entry point for the engine subprocess."""
    global LISTEN_HOST, LISTEN_PORT, FAKE_SNI, CONNECT_IP, CONNECT_PORT, INTERFACE_IPV4

    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    log(f"Shade Engine v{APP_VERSION}")
    log("Initializing core...")

    config_path = os.path.join(get_exe_dir(), "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        log(f"ERROR: cannot read config.json ({e}). Open Configuration and save your settings first.")
        return

    try:
        LISTEN_HOST = str(config["LISTEN_HOST"]).strip()
        LISTEN_PORT = int(config["LISTEN_PORT"])
        FAKE_SNI = str(config["FAKE_SNI"]).strip().encode()
        CONNECT_IP = str(config["CONNECT_IP"]).strip()
        CONNECT_PORT = int(config["CONNECT_PORT"])
    except Exception as e:
        log(f"ERROR: config.json is missing or has invalid keys ({e}).")
        log("Required keys: LISTEN_HOST, LISTEN_PORT, FAKE_SNI, CONNECT_IP, CONNECT_PORT")
        return

    INTERFACE_IPV4 = get_default_interface_ipv4(CONNECT_IP)
    if not INTERFACE_IPV4:
        log("ERROR: could not determine the local network interface. "
            "Check your internet connection and CONNECT_IP.")
        return

    w_filter = ("tcp and ("
                f"(ip.SrcAddr == {INTERFACE_IPV4} and ip.DstAddr == {CONNECT_IP})"
                " or "
                f"(ip.SrcAddr == {CONNECT_IP} and ip.DstAddr == {INTERFACE_IPV4})"
                ")")

    threading.Thread(target=_injector_thread, args=(w_filter,), daemon=True).start()

    try:
        asyncio.run(main())
    except OSError as e:
        log(f"ERROR: could not bind {LISTEN_HOST}:{LISTEN_PORT} ({e}). "
            "The port may already be in use.")
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log(f"ERROR: engine stopped unexpectedly ({e!r}).")


if __name__ == "__main__":
    run_engine()
