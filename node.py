import sys
import subprocess
import importlib.util
import socket
import threading
import json
import os
import base64
import uuid

def check_requirements():
    # Auto-install required dependencies including cryptography for E2EE
    required = {'colorama', 'prompt_toolkit', 'cryptography'}
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

# Imports for RSA Hybrid Cryptography
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes

colorama.init(autoreset=True)

def cprint(text):
    print_formatted_text(ANSI(str(text)))

COMMANDS = ['/help', '/connect', '/peers', '/keys', '/msg', '/file', '/accept', '/clear', '/exit']

# P2P & CRYPTO STATE VARIABLES
node_name = ""
peers = [] 
peers_lock = threading.Lock()
seen_messages = set() 
pending_uploads = {}

# RSA Keys (Generated on node startup)
private_key = None
public_key = None
pem_public_string = ""
known_public_keys = {} # ID Book mapping usernames to their RSA Public Key objects

class SmartCommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if ' ' not in text and text.startswith('/'):
            for cmd in COMMANDS:
                if cmd.startswith(text.lower()):
                    yield Completion(cmd, start_position=-len(text))

command_completer = SmartCommandCompleter()

def print_help():
    cprint(f"\n{Fore.CYAN}=== P2P MESH & CRYPTO MENU ==={Style.RESET_ALL}")
    cprint(f"  {Fore.YELLOW}/connect [IP] [PORT]{Style.RESET_ALL} - Link to a mesh node")
    cprint(f"  {Fore.YELLOW}/peers{Style.RESET_ALL}               - Show direct connections")
    cprint(f"  {Fore.YELLOW}/keys{Style.RESET_ALL}                - Show collected Public Keys (ID book)")
    cprint(f"  {Fore.YELLOW}<text>{Style.RESET_ALL}               - Public Gossip (Unencrypted)")
    cprint(f"  {Fore.YELLOW}/msg [user] [text]{Style.RESET_ALL}   - E2E Encrypted Private Message")
    cprint(f"  {Fore.YELLOW}/file [user] [path]{Style.RESET_ALL}  - Route a file offer\n")

# P2P CORE: Gossip Protocol Router
def broadcast_gossip(data_dict, exclude_sock=None):
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
    buffer = b""
    
    # Broadcast our Public Key to the new peer upon connection
    key_announcement = {
        "type": "key_broadcast",
        "sender": node_name,
        "public_key": pem_public_string
    }
    broadcast_gossip(key_announcement)

    while not disconnect_flag.is_set():
        try:
            chunk = sock.recv(1048576)
            if not chunk: break
            buffer += chunk
            
            while b'\n' in buffer:
                raw_msg_bytes, buffer = buffer.split(b'\n', 1)
                if not raw_msg_bytes.strip(): continue
                    
                data = json.loads(raw_msg_bytes.decode('utf-8'))
                msg_id = data.get('msg_id')
                
                # Prevent infinite routing loops
                if msg_id in seen_messages: continue
                seen_messages.add(msg_id)
                
                broadcast_gossip(data, exclude_sock=sock)
                
                # --- PROCESS DATA LOCALLY ---
                
                # 1. Public Key Collection
                if data['type'] == 'key_broadcast':
                    sender = data['sender']
                    if sender != node_name and sender not in known_public_keys:
                        try:
                            key_obj = serialization.load_pem_public_key(data['public_key'].encode('utf-8'))
                            known_public_keys[sender] = key_obj
                            cprint(f"{Fore.GREEN}[🔑] Received and stored Public Key for '{sender}'!{Style.RESET_ALL}")
                            
                            # Reply with our key to establish mutual encryption
                            reply_key = {"type": "key_broadcast", "sender": node_name, "public_key": pem_public_string}
                            broadcast_gossip(reply_key)
                        except: pass

                elif data['type'] == 'broadcast':
                    cprint(f"{Fore.BLUE}[{data['sender']} (Public)]{Style.RESET_ALL}: {data['content']}")
                    
                # 2. End-to-End Decryption Engine
                elif data['type'] == 'private_msg':
                    if data['target'] == node_name:
                        try:
                            # Decode from Base64 and decrypt using local Private Key
                            encrypted_bytes = base64.b64decode(data['content'])
                            decrypted_text = private_key.decrypt(
                                encrypted_bytes,
                                padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
                            ).decode('utf-8')
                            cprint(f"{Fore.MAGENTA}🔒 [E2EE from {data['sender']}]: {decrypted_text}{Style.RESET_ALL}")
                        except Exception as e:
                            cprint(f"{Fore.RED}[-] Failed to decrypt message from {data['sender']}.{Style.RESET_ALL}")
                            
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
                                cprint(f"{Fore.GREEN}[+] Sent '{req_file}' to '{accepter}'.{Style.RESET_ALL}")
                            except Exception as e:
                                cprint(f"{Fore.RED}[-] File error: {e}{Style.RESET_ALL}")
                                
                elif data['type'] == 'file_transfer':
                    if data['target'] == node_name:
                        save_path = f"received_{data['sender']}_{data['filename']}"
                        try:
                            with open(save_path, "wb") as f:
                                f.write(base64.b64decode(data['data']))
                            cprint(f"\n{Fore.MAGENTA}[+] Downloaded '{data['filename']}'! Saved as {save_path}{Style.RESET_ALL}")
                        except Exception as e:
                            cprint(f"{Fore.RED}[-] Save error: {e}{Style.RESET_ALL}")
                            
        except Exception: break

    with peers_lock:
        if sock in peers: peers.remove(sock)
    try: sock.close()
    except: pass

def server_listener(port, disconnect_flag):
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
            cprint(f"{Fore.GREEN}[+] New peer linked from {addr}{Style.RESET_ALL}")
        except: break

def main():
    global node_name, private_key, public_key, pem_public_string
    print(f"{Fore.CYAN}=== E2EE P2P Mesh Node ==={Style.RESET_ALL}")
    
    # Generate RSA-2048 Keypair on node startup
    print(f"{Fore.YELLOW}[*] Generating RSA-2048 Keypair...{Style.RESET_ALL}")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    pem_public_string = public_key.public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo).decode('utf-8')
    print(f"{Fore.GREEN}[+] Crypto Keys Ready. Your node is secure.{Style.RESET_ALL}")
    
    node_name = input("Enter Node Name (ID): ").strip()
    my_port = int(input("Enter PORT to bind (e.g., 5555): ").strip())
    
    disconnect_flag = threading.Event()
    listener_thread = threading.Thread(target=server_listener, args=(my_port, disconnect_flag), daemon=True)
    listener_thread.start()
    
    print(f"{Fore.GREEN}[*] Node active. Listening on 0.0.0.0:{my_port}{Style.RESET_ALL}")
    
    with patch_stdout():
        while not disconnect_flag.is_set():
            try:
                msg = prompt('Mesh> ', completer=command_completer).strip()
                if not msg: continue
                
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
                            cprint(f"{Fore.GREEN}[+] Linked to {target_ip}:{target_port}{Style.RESET_ALL}")
                        except Exception as e:
                            cprint(f"{Fore.RED}[-] Link failed: {e}{Style.RESET_ALL}")
                            
                elif msg.lower() == '/peers':
                    cprint(f"{Fore.YELLOW}Active direct links: {len(peers)}{Style.RESET_ALL}")
                    
                elif msg.lower() == '/keys':
                    cprint(f"{Fore.CYAN}--- Discovered Public Keys (ID Book) ---{Style.RESET_ALL}")
                    for name in known_public_keys:
                        cprint(f" - {Fore.GREEN}{name}{Style.RESET_ALL}")
                    if not known_public_keys:
                        cprint(f"{Fore.RED}No keys collected yet.{Style.RESET_ALL}")
                    
                elif msg.lower() == '/clear':
                    os.system('cls' if os.name == 'nt' else 'clear')
                    
                elif msg.lower() in ['/exit', '/quit']:
                    disconnect_flag.set()
                    break 
                    
                elif msg.startswith('/msg '):
                    parts = msg.split(' ', 2)
                    if len(parts) >= 3:
                        target, content = parts[1], parts[2]
                        # ENCRYPTION PROCESS
                        if target in known_public_keys:
                            target_pub_key = known_public_keys[target]
                            # Encrypt payload using target's Public Key
                            encrypted_bytes = target_pub_key.encrypt(
                                content.encode('utf-8'),
                                padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
                            )
                            # Encode to Base64 for JSON transmission
                            b64_cipher = base64.b64encode(encrypted_bytes).decode('utf-8')
                            
                            chat_data = {"type": "private_msg", "sender": node_name, "target": target, "content": b64_cipher}
                            broadcast_gossip(chat_data)
                            cprint(f"{Fore.YELLOW}🔒 (E2EE to {target}): {content}{Style.RESET_ALL}")
                        else:
                            cprint(f"{Fore.RED}[-] Cannot encrypt. I don't have '{target}'s Public Key yet.{Style.RESET_ALL}")
                            cprint(f"{Fore.YELLOW}[*] Hint: They need to connect to the mesh so I can receive their key broadcast.{Style.RESET_ALL}")
                            
                elif msg.startswith('/accept ') or msg.startswith('/file '):
                    parts = msg.split(' ', 2)
                    if msg.startswith('/accept ') and len(parts) == 3:
                        broadcast_gossip({"type": "file_accept", "sender": node_name, "target": parts[1], "filename": parts[2]})
                    elif msg.startswith('/file ') and len(parts) == 3:
                        if os.path.exists(parts[2]):
                            filename = os.path.basename(parts[2])
                            pending_uploads[filename] = parts[2]
                            broadcast_gossip({"type": "file_offer", "sender": node_name, "target": parts[1], "filename": filename, "size": os.path.getsize(parts[2])})
                            cprint(f"{Fore.GREEN}[+] Offer injected.{Style.RESET_ALL}")
                        
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