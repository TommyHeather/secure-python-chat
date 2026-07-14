import sys
import subprocess
import importlib.util
import socket
import threading
import json
import os
import base64
import uuid
import traceback

def check_requirements():
    required = {'colorama', 'prompt_toolkit'}
    missing = [req for req in required if importlib.util.find_spec(req) is None]
    if missing:
        print(f"[*] Missing modules: {', '.join(missing)}")
        if input("[?] Auto-install? (y/n): ").lower() == 'y':
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', *missing])
            print("[+] Installed. Restarting...\n")
        sys.exit(1)

check_requirements()

import colorama
from colorama import Fore, Style
from prompt_toolkit import prompt, print_formatted_text, ANSI
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.patch_stdout import patch_stdout

colorama.init(autoreset=True)

def cprint(text):
    print_formatted_text(ANSI(str(text)))

COMMANDS = ['/help', '/connect', '/peers', '/msg', '/file', '/accept', '/clear', '/exit']

# P2P STATE VARIABLES
node_name = ""
peers = [] # List of connected sockets
peers_lock = threading.Lock()
seen_messages = set() # To prevent infinite Gossip loops
pending_uploads = {}

class SmartCommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if ' ' not in text and text.startswith('/'):
            for cmd in COMMANDS:
                if cmd.startswith(text.lower()):
                    yield Completion(cmd, start_position=-len(text))

command_completer = SmartCommandCompleter()

def print_help():
    cprint(f"\n{Fore.CYAN}=== P2P NODE MENU ==={Style.RESET_ALL}")
    cprint(f"  {Fore.YELLOW}/connect [IP] [PORT]{Style.RESET_ALL} - Connect to another node in the mesh")
    cprint(f"  {Fore.YELLOW}/peers{Style.RESET_ALL}               - Show direct connections")
    cprint(f"  {Fore.YELLOW}<text>{Style.RESET_ALL}               - Gossip a message to the entire mesh")
    cprint(f"  {Fore.YELLOW}/msg [user] [text]{Style.RESET_ALL}   - Route a private message")
    cprint(f"  {Fore.YELLOW}/file [user] [path]{Style.RESET_ALL}  - Route a file offer")
    cprint(f"  {Fore.YELLOW}/accept [user] [file]{Style.RESET_ALL}- Accept a file offer\n")

# P2P CORE: Gossip Protocol Router
def broadcast_gossip(data_dict, exclude_sock=None):
    """
    Sends data to all direct peers. If it's a new message, assigns a UUID.
    This creates a resilient mesh network where data hops from node to node.
    """
    if 'msg_id' not in data_dict:
        data_dict['msg_id'] = str(uuid.uuid4())
    
    msg_id = data_dict['msg_id']
    seen_messages.add(msg_id)
    
    out_bytes = (json.dumps(data_dict) + '\n').encode('utf-8')
    
    with peers_lock:
        for p_sock in peers:
            if p_sock != exclude_sock:
                try:
                    p_sock.sendall(out_bytes)
                except:
                    pass

# P2P CORE: Peer Connection Handler
def handle_peer(sock, disconnect_flag):
    """Handles incoming raw bytes from a connected peer (symmetric for incoming/outgoing connections)"""
    buffer = b""
    while not disconnect_flag.is_set():
        try:
            chunk = sock.recv(1048576)
            if not chunk:
                break
                
            buffer += chunk
            while b'\n' in buffer:
                raw_msg_bytes, buffer = buffer.split(b'\n', 1)
                if not raw_msg_bytes.strip():
                    continue
                    
                data = json.loads(raw_msg_bytes.decode('utf-8'))
                msg_id = data.get('msg_id')
                
                # GOSSIP CHECK: If we already saw this packet, drop it (prevents echo storms)
                if msg_id in seen_messages:
                    continue
                seen_messages.add(msg_id)
                
                # Gossip the packet forward to other peers to sustain the mesh
                broadcast_gossip(data, exclude_sock=sock)
                
                # --- PROCESS DATA LOCALLY ---
                if data['type'] == 'broadcast':
                    cprint(f"{Fore.BLUE}[{data['sender']}]{Style.RESET_ALL}: {data['content']}")
                    
                elif data['type'] == 'private_msg':
                    if data['target'] == node_name:
                        cprint(f"{Fore.MAGENTA}(Private from {data['sender']}): {data['content']}{Style.RESET_ALL}")
                        
                elif data['type'] == 'file_offer':
                    if data['target'] == node_name or data['target'] == 'all':
                        cprint(f"\n{Fore.MAGENTA}[!] '{data['sender']}' offers file: {data['filename']} ({data['size']}b){Style.RESET_ALL}")
                        cprint(f"{Fore.MAGENTA}[!] Type: /accept {data['sender']} {data['filename']}{Style.RESET_ALL}\n")
                        
                elif data['type'] == 'file_accept':
                    if data['target'] == node_name:
                        accepter = data['sender']
                        req_file = data['filename']
                        if req_file in pending_uploads:
                            try:
                                with open(pending_uploads[req_file], "rb") as f:
                                    b64_data = base64.b64encode(f.read()).decode('utf-8')
                                transfer_data = {"type": "file_transfer", "sender": node_name, "target": accepter, "filename": req_file, "data": b64_data}
                                broadcast_gossip(transfer_data)
                                cprint(f"{Fore.GREEN}[+] Sent '{req_file}' to '{accepter}' through the mesh.{Style.RESET_ALL}")
                            except Exception as e:
                                cprint(f"{Fore.RED}[-] File error: {e}{Style.RESET_ALL}")
                                
                elif data['type'] == 'file_transfer':
                    if data['target'] == node_name:
                        save_path = f"received_{data['sender']}_{data['filename']}"
                        try:
                            with open(save_path, "wb") as f:
                                f.write(base64.b64decode(data['data']))
                            cprint(f"\n{Fore.MAGENTA}[+] Downloaded '{data['filename']}'! Saved as {save_path}{Style.RESET_ALL}")
                            
                            ack = {"type": "private_msg", "sender": node_name, "target": data['sender'], "content": f"[AUTO-REPLY] Downloaded '{data['filename']}'"}
                            broadcast_gossip(ack)
                        except Exception as e:
                            cprint(f"{Fore.RED}[-] Save error: {e}{Style.RESET_ALL}")
                            
        except Exception:
            break

    # Cleanup disconnected peer
    with peers_lock:
        if sock in peers:
            peers.remove(sock)
    try:
        sock.close()
    except:
        pass
    cprint(f"{Fore.YELLOW}[*] A peer disconnected. Direct links remaining: {len(peers)}{Style.RESET_ALL}")

# P2P CORE: Server Listener Thread
def server_listener(port, disconnect_flag):
    """Waits for other nodes to connect to us"""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(('0.0.0.0', port))
    server_sock.listen()
    
    while not disconnect_flag.is_set():
        try:
            conn, addr = server_sock.accept()
            with peers_lock:
                peers.append(conn)
            threading.Thread(target=handle_peer, args=(conn, disconnect_flag), daemon=True).start()
            cprint(f"{Fore.GREEN}[+] New peer connected from {addr}{Style.RESET_ALL}")
        except:
            break

def main():
    global node_name
    print(f"{Fore.CYAN}=== P2P Mesh Node ==={Style.RESET_ALL}")
    
    node_name = input("Enter your Node Name (Username): ").strip()
    my_port = int(input("Enter local PORT to listen on (e.g., 5555): ").strip())
    
    disconnect_flag = threading.Event()
    
    # Start listening for incoming connections
    listener_thread = threading.Thread(target=server_listener, args=(my_port, disconnect_flag), daemon=True)
    listener_thread.start()
    
    print(f"{Fore.GREEN}[*] Node active. Listening on 0.0.0.0:{my_port}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Type '/connect [IP] [PORT]' to link with other nodes, or '/help'.{Style.RESET_ALL}\n")
    
    with patch_stdout():
        while not disconnect_flag.is_set():
            try:
                msg = prompt('Mesh> ', completer=command_completer).strip()
                if not msg:
                    continue
                
                if msg.lower() == '/help':
                    print_help()
                    
                elif msg.startswith('/connect '):
                    parts = msg.split()
                    if len(parts) == 3:
                        target_ip, target_port = parts[1], int(parts[2])
                        try:
                            new_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            new_sock.connect((target_ip, target_port))
                            with peers_lock:
                                peers.append(new_sock)
                            threading.Thread(target=handle_peer, args=(new_sock, disconnect_flag), daemon=True).start()
                            cprint(f"{Fore.GREEN}[+] Successfully linked to peer {target_ip}:{target_port}{Style.RESET_ALL}")
                        except Exception as e:
                            cprint(f"{Fore.RED}[-] Link failed: {e}{Style.RESET_ALL}")
                    else:
                        cprint(f"{Fore.RED}Usage: /connect [IP] [PORT]{Style.RESET_ALL}")
                        
                elif msg.lower() == '/peers':
                    cprint(f"{Fore.YELLOW}Active direct links: {len(peers)}{Style.RESET_ALL}")
                    
                elif msg.lower() == '/clear':
                    os.system('cls' if os.name == 'nt' else 'clear')
                    
                elif msg.lower() in ['/exit', '/quit']:
                    cprint(f"{Fore.YELLOW}[*] Shutting down node...{Style.RESET_ALL}")
                    disconnect_flag.set()
                    break 
                    
                elif msg.startswith('/msg '):
                    parts = msg.split(' ', 2)
                    if len(parts) >= 3:
                        target, content = parts[1], parts[2]
                        chat_data = {"type": "private_msg", "sender": node_name, "target": target, "content": content}
                        broadcast_gossip(chat_data)
                        cprint(f"{Fore.YELLOW}(Routed to {target}): {content}{Style.RESET_ALL}")
                        
                elif msg.startswith('/accept '):
                    parts = msg.split(' ', 2)
                    if len(parts) == 3:
                        accept_data = {"type": "file_accept", "sender": node_name, "target": parts[1], "filename": parts[2]}
                        broadcast_gossip(accept_data)
                        cprint(f"{Fore.YELLOW}[*] Acceptance routed into the mesh. Awaiting transfer...{Style.RESET_ALL}")

                elif msg.startswith('/file '):
                    parts = msg.split(' ', 2)
                    if len(parts) == 3:
                        target, filepath = parts[1], parts[2]
                        if os.path.exists(filepath):
                            filename = os.path.basename(filepath)
                            pending_uploads[filename] = filepath
                            offer = {"type": "file_offer", "sender": node_name, "target": target, "filename": filename, "size": os.path.getsize(filepath)}
                            broadcast_gossip(offer)
                            cprint(f"{Fore.GREEN}[+] File offer injected into mesh for {target}.{Style.RESET_ALL}")
                        else:
                            cprint(f"{Fore.RED}[-] Local file not found.{Style.RESET_ALL}")
                            
                elif msg.startswith('/'):
                    cprint(f"{Fore.RED}Unknown command.{Style.RESET_ALL}")
                        
                else:
                    chat_data = {"type": "broadcast", "sender": node_name, "content": msg}
                    broadcast_gossip(chat_data)
                    
            except KeyboardInterrupt:
                disconnect_flag.set()
                break

    sys.exit(0)

if __name__ == "__main__":
    main()