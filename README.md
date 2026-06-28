# 🛡️ Secure Python Chat Cluster (C/S Architecture)

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey)

## 📖 Table of Contents
1. [Project Overview](#-project-overview)
2. [Architecture & Core Components](#-architecture--core-components)
3. [The Custom Protocol & TCP Framing](#-the-custom-protocol--tcp-framing)
4. [Security & Stability Features](#-security--stability-features)
5. [Installation & Usage](#-installation--usage)
6. [Command Reference](#-command-reference)
7. [File Transfer Handshake Protocol](#-file-transfer-handshake-protocol)
8. [Roadmap & Future Features](#-roadmap--future-features)

---

## 📌 Project Overview
This project is an advanced, multiplexed Client-Server chat architecture built entirely in Python. It was developed to practically explore network programming, socket management, asynchronous I/O, and secure data routing. The framework supports global broadcasting, private messaging, and secure asynchronous file transfers.

## 🏗️ Architecture & Core Components
The project is divided into two decoupled modules:

* **`server.py` (The Routing Node):** Utilizes the `select` module for I/O multiplexing. Instead of spawning heavy OS threads for each user, it operates in a single, highly efficient event loop. It manages a persistent `sqlite3` database for user credentials, enforcing unique identities via SQL constraints.
* **`client.py` (The Universal Interface):** A highly interactive CLI built with `prompt_toolkit`. It uses the `patch_stdout()` context manager to render incoming network messages asynchronously without breaking the user's active typing line. It supports dynamic server IP/Port connection profiling.

## 🔌 The Custom Protocol & TCP Framing
To solve the classic **TCP Packet Fragmentation** issue (where large payloads like Base64 files get split across multiple TCP packets, causing `JSONDecodeError`), this project implements a custom **Message Framing** protocol:
1. **Serialization:** All data is serialized into JSON.
2. **Framing:** Every outgoing JSON string is appended with a mandatory newline byte (`\n`).
3. **Buffering:** The receiver accumulates raw bytes (`b""`) into a dedicated memory buffer.
4. **Extraction:** The JSON parser only executes when a complete frame (delimited by `\n`) is isolated from the buffer, guaranteeing 100% data integrity even for massive file payloads over unstable networks.

## 🔒 Security & Stability Features
* **Cluster-Level Access Control:** The server can be locked down using a Master Password (configurable via the `SERVER_PASSWORD` variable in `server.py`). This prevents unauthorized nodes from attempting to register or log in to the private cluster.
* **Scanner Protection:** The server silently drops malformed requests (e.g., HTTP GET requests from automated internet scanners or botnets) by catching JSON decoding exceptions, preventing application crashes.
* **Double-Login Prevention:** Prevents concurrent sessions from the same account.
* **Injection Mitigation:** Enforces strict alphanumeric validation (`re.match`) for usernames before database insertion.
* **Transmission Guarantees:** Network transmissions strictly use the `sendall()` method to prevent partial packet drops during heavy network loads.

---

## 🚀 Installation & Usage

### Prerequisites
* Python 3.8 or higher.
* No manual pip installations required. The client script features an **auto-installer** that will automatically fetch and install missing dependencies (`colorama`, `prompt_toolkit`) upon first execution.

### 1. Hosting the Server
Configure the `SERVER_PASSWORD` inside `server.py` (default is `"root"`), then run the script on your local machine, VPS, or cloud instance:
```bash
python3 server.py
```
*(Note: If deploying over the internet, ensure port `5555/tcp` is open in your firewall, e.g., `sudo ufw allow 5555/tcp`, and configured in your router's Port Forwarding rules).*

### 2. Launching the Client
```bash
python3 client.py
```
Follow the interactive prompts to enter the target Server IP, Port, and Cluster Password. Type `register` to create an account or `login` to access an existing one.

---

## 💻 Command Reference

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `<text>` | None | Broadcast a message to the entire cluster. |
| `/msg` | `[user] [text]` | Send a private, direct message to an online user. |
| `/file` | `all [path]` | Offer a local file to everyone on the network. |
| `/file` | `[user] [path]` | Send a targeted file offer to a specific user. |
| `/accept`| `[user] [filename]` | Accept a pending file offer and download the payload. |
| `/online`| None | Retrieve a list of currently connected users from the server. |
| `/clear` | None | Clear the terminal screen. |
| `/help` | None | Display the internal command menu. |
| `/exit` | None | Disconnect gracefully and return to the main menu. |

---

## 📁 File Transfer Handshake Protocol
To prevent network congestion and unauthorized file downloads, file transfers require a strict 3-way handshake:
1. **Offer:** Sender uses `/file [user] [path]`. The client registers the file locally and sends a lightweight `file_offer` metadata packet to the network.
2. **Acceptance:** The recipient sees the offer and explicitly types `/accept [user] [filename]`. An acceptance packet is routed back to the sender.
3. **Transfer:** The sender's client automatically encodes the file into a Base64 payload in the background and streams it to the recipient. An `[AUTO-REPLY]` acknowledgment is generated upon successful disk write.

**⚠️ 500KB Payload Limit:** To maintain optimal performance in this academic lab environment, file transfers are capped at ~500KB. This prevents JSON parsers from overloading system RAM during Base64 decoding and avoids complex chunking/reassembly logic that falls outside the scope of this project.

---

## 🗺️ Roadmap & Future Features
This project is continuously evolving. Planned architectural upgrades include:
- [ ] **End-to-End Encryption (E2EE):** Implementation of Hybrid Cryptography (RSA/AES) to encrypt JSON payloads client-side, ensuring zero-knowledge routing by the server.
- [ ] **Decentralization (P2P):** Transitioning away from a central server to a distributed node-based architecture.
- [ ] **Offline Bluetooth Mesh:** Allowing clients to discover and route packets through local Bluetooth adapters in the absence of Wi-Fi.

## 🙏 Acknowledgments
This project evolved significantly beyond its initial academic requirements. I would like to express my sincere gratitude to those who made this possible:

---

* **The Course Lecturer:** A special thank you for the continuous support, guidance, and for enthusiastically approving the "project upgrade" that allowed me to push the technical boundaries of the original assignment.
* **My classmates, Uria (אוריה) and Or (אור):** Thank you for your invaluable contributions to QA and cross-platform testing. Your rigorous bug-hunting, relentless testing across different devices, and brilliant architectural suggestions directly led to critical code improvements and the flawless stabilization of the final protocol.

---

*Built with ❤️ by Anton for network security and protocol engineering students*
