import socket
import time
import re
import paho.mqtt.client as mqtt

# ==================================
# KONFIGURASI MQTT
# ==================================

BROKER = "broker.emqx.io"
MQTT_PORT = 1883
TOPIC = "raspberry_temperature"

# ==================================
# KONFIGURASI APRS
# ==================================

CALLSIGN = "YD3ADB-1"
DESTINATION = "APRS"

KISS_HOST = "127.0.0.1"
KISS_PORT = 8001

# Interval pengiriman telemetry
SEND_INTERVAL = 300  # 5 menit

sequence = 0
last_sent = 0
kiss_socket = None


# ==================================
# MEMBUAT ALAMAT AX.25
# ==================================

def encode_address(callsign, last=False):
    parts = callsign.split("-")
    call = parts[0]
    ssid = int(parts[1]) if len(parts) > 1 else 0

    address = bytearray()

    for char in call.ljust(6):
        address.append(ord(char) << 1)

    ssid_byte = 0x60 | (ssid << 1)

    if last:
        ssid_byte |= 0x01

    address.append(ssid_byte)

    return bytes(address)


# ==================================
# MEMBUAT FRAME AX.25
# ==================================

def create_ax25_frame(packet):
    header = (
        encode_address(DESTINATION)
        + encode_address(CALLSIGN, last=True)
    )

    return (
        header
        + bytes([0x03])
        + bytes([0xF0])
        + packet.encode("ascii")
    )


# ==================================
# MEMBUAT FRAME KISS CHANNEL 15
# ==================================

def create_kiss_frame(ax25_data):
    data = bytes([0xF0]) + ax25_data

    escaped = bytearray([0xC0])

    for byte in data:
        if byte == 0xC0:
            escaped.extend([0xDB, 0xDC])
        elif byte == 0xDB:
            escaped.extend([0xDB, 0xDD])
        else:
            escaped.append(byte)

    escaped.append(0xC0)

    return bytes(escaped)


# ==================================
# KONEKSI KE DIRE WOLF
# ==================================

def connect_kiss():
    global kiss_socket

    kiss_socket = socket.create_connection(
        (KISS_HOST, KISS_PORT),
        timeout=10
    )

    print("Berhasil terhubung ke Dire Wolf!")


def send_aprs(packet):
    ax25 = create_ax25_frame(packet)
    kiss = create_kiss_frame(ax25)

    kiss_socket.sendall(kiss)

    print("Paket APRS dikirim:", packet)


# ==================================
# METADATA TELEMETRY
# ==================================

def send_metadata():
    address = CALLSIGN.ljust(9)

    packets = [
        f":{address}:PARM.Temp,,,,",
        f":{address}:UNIT.deg C,,,,",
        f":{address}:EQNS.0,0.392157,0,0,1,0,0,1,0,0,1,0,0,1,0",
        f":{address}:BITS.11111111,Temperature Monitoring"
    ]

    for packet in packets:
        send_aprs(packet)
        time.sleep(2)



# ==================================
# MEMPROSES DATA MQTT
# ==================================

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("Berhasil terhubung ke MQTT Broker!")
        client.subscribe(TOPIC)
        print("Subscribe topic:", TOPIC)
    else:
        print("Koneksi MQTT gagal:", reason_code)


def on_message(client, userdata, msg):
    global sequence, last_sent

    payload = msg.payload.decode("utf-8", errors="replace")

    print("\nData MQTT diterima:", payload)

    match = re.search(
        r"temp\s*=\s*(-?\d+(?:\.\d+)?)",
        payload,
        re.IGNORECASE
    )

    if not match:
        print("Format suhu tidak dikenali.")
        return

    temperature = float(match.group(1))

    print("Suhu Raspberry Pi:", temperature, "°C")

    # Batasi pengiriman menjadi satu paket setiap 5 menit
    current_time = time.time()

    if current_time - last_sent < SEND_INTERVAL:
        print("Data diterima, menunggu jadwal pengiriman berikutnya.")
        return

    # Konversi suhu 0-100°C menjadi analog 0-255
    analog_value = round(temperature * 255 / 100)
    analog_value = max(0, min(255, analog_value))

    sequence = (sequence + 1) % 1000

    telemetry = (
        f"T#{sequence:03d},"
        f"{analog_value:03d},"
        "000,000,000,000,"
        "00000000"
    )

    send_aprs(telemetry)

    last_sent = current_time

    print("Suhu berhasil dikirim ke APRS-IS.")


# ==================================
# PROGRAM UTAMA
# ==================================

print("Memulai MQTT to APRS Telemetry...")

try:
    connect_kiss()

    print("Mengirim metadata telemetry...")
    send_metadata()

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )

    client.on_connect = on_connect
    client.on_message = on_message

    print("Menghubungkan ke MQTT Broker...")

    client.connect(BROKER, MQTT_PORT, 60)

    client.loop_forever()

except KeyboardInterrupt:
    print("\nProgram dihentikan.")

except Exception as error:
    print("Terjadi kesalahan:", error)

finally:
    if kiss_socket:
        kiss_socket.close()