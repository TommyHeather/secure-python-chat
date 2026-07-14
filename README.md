# 🕸️ Decentralized P2P Chat Node (Mesh Network)

> **⚠️ EXPERIMENTAL BRANCH:** This branch transitions the project from a central Client-Server architecture to a fully decentralized Peer-to-Peer (P2P) mesh network, as outlined in the project's roadmap.

## 📌 P2P Architecture Overview
Instead of relying on a centralized `server.py` to route traffic, this branch introduces `node.py`. Every instance acts symmetrically as both a Server (listening for connections) and a Client (connecting to others). 

### 🧬 The Gossip Protocol
To prevent infinite routing loops in a decentralized mesh, this node utilizes a **Gossip Protocol**:
1. Every new message (text, file offer, or binary transfer) is tagged with a unique `UUID`.
2. Nodes maintain a local cache (`seen_messages = set()`) of packet IDs.
3. When a node receives a packet, it checks the UUID. If it's new, the node processes it and forwards (gossips) it to all directly connected peers. If the UUID is already in the cache, the packet is silently dropped.

## 🚀 How to Run

1. Run the node on any machine:
```bash
python3 node.py
```
2. Enter your chosen Username and a local port to bind to (e.g., `5555`).
3. To build the mesh, use the internal CLI to link to a friend's node:
```text
/connect <FRIENDS_IP> <FRIENDS_PORT>
```
*Note: As long as nodes are linked together (e.g., A connected to B, and B connected to C), Node A can securely route messages and files to Node C through Node B seamlessly.*