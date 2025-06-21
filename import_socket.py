import socket
import json

# Send a test command
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
test_data = {"command": "status", "confidence": 1.0, "label": "Test"}
sock.sendto(json.dumps(test_data).encode('utf-8'), ("127.0.0.1", 9999))
print("Sent test command to port 9999")