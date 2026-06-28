# Import the socket module to handle network connections
import socket
# Import the select module for asynchronous, non-blocking I/O
import select
# Import the json module to format and parse our data packets
import json
# Import the sqlite3 module to manage the local user database
import sqlite3
# Import the sys module to handle system exits safely
import sys
# Import the re (Regular Expressions) module to validate usernames
import re

# Define the IP address to listen on (0.0.0.0 means all available network interfaces)
HOST = '0.0.0.0'
# Define the port number where the server will accept connections
PORT = 5555
# Define a master password for the entire server cluster (leave as "" to disable)
SERVER_PASSWORD = "root"

# Define a function to initialize the SQLite database
def init_db():
    # Connect to the local database file
    conn = sqlite3.connect('chat.db')
    # Create a cursor object to execute SQL commands
    cursor = conn.cursor()
    # Create the users table, setting username as the PRIMARY KEY for uniqueness
    cursor.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)")
    # Commit changes to the database
    conn.commit()
    # Close the database connection
    conn.close()

# Define a function to handle user registration and login
def handle_auth(client_socket, data, clients_info):
    # Extract username from the payload
    username = data.get('username')
    # Extract password from the payload
    password = data.get('password')
    # Extract the requested action
    action = data.get('action')
    # Extract the cluster password provided by the user
    client_provided_server_pass = data.get('server_password', '')
    
    # Check if a server password is required AND if the user provided the wrong one
    if SERVER_PASSWORD != "" and client_provided_server_pass != SERVER_PASSWORD:
        # Create an error response
        response = {"type": "system", "status": "error", "msg": "Access Denied: Invalid Cluster Password."}
        # Use sendall() to guarantee transmission, append \n for framing
        client_socket.sendall((json.dumps(response) + '\n').encode('utf-8'))
        return

    # Validate username formatting using Regex
    if not re.match(r"^[a-zA-Z0-9]+$", username):
        # Create an error response
        response = {"type": "system", "status": "error", "msg": "Username must contain only English letters and numbers."}
        # Use sendall() and append \n
        client_socket.sendall((json.dumps(response) + '\n').encode('utf-8'))
        return

    # Connect to the SQLite database
    conn = sqlite3.connect('chat.db')
    cursor = conn.cursor()
    
    # Process registration
    if action == 'register':
        try:
            # Execute SQL to insert user
            cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            conn.commit()
            # Success response
            response = {"type": "system", "status": "ok", "msg": "Registration successful. You can now login."}
        except sqlite3.IntegrityError:
            # Handle duplicate username
            response = {"type": "system", "status": "error", "msg": "Username already taken."}
            
    # Process login
    elif action == 'login':
        # Retrieve password from database
        cursor.execute("SELECT password FROM users WHERE username = ?", (username,))
        result = cursor.fetchone()
        
        # Prevent double login
        if username in clients_info.values():
             response = {"type": "system", "status": "error", "msg": "User is already logged in from another session."}
        # Verify password
        elif result and result[0] == password:
            # Map socket to username
            clients_info[client_socket] = username
            response = {"type": "system", "status": "ok", "msg": f"Welcome to the cluster, {username}!"}
            # Broadcast join message
            broadcast_system_message(f"User '{username}' has joined the chat.", clients_info, client_socket)
        # Handle invalid credentials
        else:
            response = {"type": "system", "status": "error", "msg": "Invalid user credentials."}
            
    # Close database connection
    conn.close()
    # Use sendall() to ensure the complete JSON string is transmitted
    client_socket.sendall((json.dumps(response) + '\n').encode('utf-8'))

# Helper function to broadcast system messages to all clients
def broadcast_system_message(message, clients_info, exclude_socket=None):
    # Create system message payload
    sys_msg = {"type": "system", "msg": message}
    # Append newline delimiter for TCP framing
    out_bytes = (json.dumps(sys_msg) + '\n').encode('utf-8')
    # Loop through connected clients
    for client in clients_info:
        # Do not send to the excluded socket
        if client != exclude_socket:
            try:
                # Use sendall() for guaranteed delivery
                client.sendall(out_bytes)
            except:
                pass

# Main server execution loop
def main():
    # Initialize DB
    init_db()
    
    # Setup server TCP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Set option to allow immediate port reuse
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Bind socket to host and port
    server_socket.bind((HOST, PORT))
    # Start listening
    server_socket.listen()
    
    print(f"[*] Cluster Server listening on {HOST}:{PORT}")
    
    # List for multiplexing
    sockets_list = [server_socket]
    # Dictionary mapping sockets to usernames
    clients_info = {}
    # Dictionary to store incomplete TCP stream buffers for each client
    clients_buffers = {}
    
    # Main loop with KeyboardInterrupt handler
    try:
        while True:
            # Use select to monitor multiple sockets without threading
            read_sockets, _, exception_sockets = select.select(sockets_list, [], sockets_list)
            
            for notified_socket in read_sockets:
                # Handle new incoming connections
                if notified_socket == server_socket:
                    # Accept connection
                    client_socket, client_address = server_socket.accept()
                    # Add to multiplexing list
                    sockets_list.append(client_socket)
                    # Initialize empty buffer string for this specific client
                    clients_buffers[client_socket] = ""
                    print(f"[+] New connection established from {client_address}")
                    
                # Handle data from existing clients
                else:
                    try:
                        # Receive a chunk of data (up to 1MB)
                        chunk = notified_socket.recv(1048576)
                        
                        # Empty chunk means client disconnected
                        if not chunk:
                            raise ConnectionResetError
                            
                        # Decode chunk and append to the client's specific TCP buffer
                        clients_buffers[notified_socket] += chunk.decode('utf-8')
                        
                        # Process while a complete framed packet (ending in \n) exists in the buffer
                        while '\n' in clients_buffers[notified_socket]:
                            # Split the buffer at the first newline
                            raw_msg, clients_buffers[notified_socket] = clients_buffers[notified_socket].split('\n', 1)
                            
                            # Ignore empty strings
                            if not raw_msg.strip():
                                continue
                                
                            # Parse the fully assembled JSON string
                            data = json.loads(raw_msg)
                            
                            # Handle authentication
                            if data['type'] == 'auth':
                                handle_auth(notified_socket, data, clients_info)
                                
                            # Handle broadcast messages
                            elif data['type'] == 'broadcast':
                                sender = clients_info.get(notified_socket, "Unknown")
                                out_msg = {"type": "msg", "sender": sender, "content": data['content']}
                                out_bytes = (json.dumps(out_msg) + '\n').encode('utf-8')
                                for client in clients_info:
                                    if client != notified_socket:
                                        client.sendall(out_bytes)

                            # Handle server commands (like /online)
                            elif data['type'] == 'cmd':
                                if data['command'] == 'online':
                                    online_list = ", ".join(clients_info.values())
                                    response = {"type": "system", "msg": f"Active users ({len(clients_info)}): {online_list}"}
                                    notified_socket.sendall((json.dumps(response) + '\n').encode('utf-8'))

                            # Handle private text messages
                            elif data['type'] == 'private_msg':
                                sender = clients_info.get(notified_socket, "Unknown")
                                target_user = data['target']
                                
                                target_socket = None
                                # Find target socket by username
                                for client_sock, user_name in clients_info.items():
                                    if user_name == target_user:
                                        target_socket = client_sock
                                        break
                                
                                # Send if target is found
                                if target_socket:
                                    out_msg = {"type": "msg", "sender": f"{sender} (Private)", "content": data['content']}
                                    target_socket.sendall((json.dumps(out_msg) + '\n').encode('utf-8'))
                                # Send error back if target is offline
                                else:
                                    err_msg = {"type": "system", "msg": f"Error: User '{target_user}' is offline or does not exist."}
                                    notified_socket.sendall((json.dumps(err_msg) + '\n').encode('utf-8'))
                                        
                            # Handle file handshake offers
                            elif data['type'] == 'file_offer':
                                sender = clients_info.get(notified_socket, "Unknown")
                                data['sender'] = sender
                                out_bytes = (json.dumps(data) + '\n').encode('utf-8')
                                target_user = data.get('target', 'all')
                                
                                if target_user != 'all':
                                    target_socket = None
                                    for client_sock, user_name in clients_info.items():
                                        if user_name == target_user:
                                            target_socket = client_sock
                                            break
                                    
                                    if target_socket:
                                        target_socket.sendall(out_bytes)
                                    else:
                                        err_msg = {"type": "system", "msg": f"Error: Cannot send file offer. User '{target_user}' is offline."}
                                        notified_socket.sendall((json.dumps(err_msg) + '\n').encode('utf-8'))
                                else:
                                    for client in clients_info:
                                        if client != notified_socket:
                                            client.sendall(out_bytes)
                                            
                            # Route the file acceptance message back to the original sender
                            elif data['type'] == 'file_accept':
                                sender = clients_info.get(notified_socket, "Unknown")
                                data['sender'] = sender
                                out_bytes = (json.dumps(data) + '\n').encode('utf-8')
                                target_user = data['target']
                                
                                target_socket = None
                                # Find the original sender's socket
                                for client_sock, user_name in clients_info.items():
                                    if user_name == target_user:
                                        target_socket = client_sock
                                        break
                                
                                if target_socket:
                                    # Forward the acceptance
                                    target_socket.sendall(out_bytes)
                                else:
                                    err_msg = {"type": "system", "msg": f"Error: Original sender '{target_user}' is no longer online."}
                                    notified_socket.sendall((json.dumps(err_msg) + '\n').encode('utf-8'))

                            # Handle massive Base64 file payloads
                            elif data['type'] == 'file_transfer':
                                sender = clients_info.get(notified_socket, "Unknown")
                                data['sender'] = sender
                                out_bytes = (json.dumps(data) + '\n').encode('utf-8')
                                target_user = data.get('target', 'all')
                                
                                if target_user != 'all':
                                    target_socket = None
                                    for client_sock, user_name in clients_info.items():
                                        if user_name == target_user:
                                            target_socket = client_sock
                                            break
                                    
                                    if target_socket:
                                        target_socket.sendall(out_bytes)
                                    else:
                                        err_msg = {"type": "system", "msg": f"Error: Cannot send file data. User '{target_user}' is offline."}
                                        notified_socket.sendall((json.dumps(err_msg) + '\n').encode('utf-8'))
                                else:
                                    for client in clients_info:
                                        if client != notified_socket:
                                            client.sendall(out_bytes)
                                            
                    except Exception as e:
                        # Client disconnected or threw JSON error
                        print("[-] Client disconnected from the cluster.")
                        sockets_list.remove(notified_socket)
                        
                        # Clean up auth dict
                        if notified_socket in clients_info:
                            disconnected_user = clients_info[notified_socket]
                            del clients_info[notified_socket]
                            broadcast_system_message(f"User '{disconnected_user}' left the chat.", clients_info)
                            
                        # Clean up TCP buffer memory
                        if notified_socket in clients_buffers:
                            del clients_buffers[notified_socket]
                            
                        # Close socket
                        notified_socket.close()

    except KeyboardInterrupt:
        print("\n[*] Server shutdown sequence initiated by user (CTRL+C).")
    finally:
        # Clean up all sockets on exit
        for sock in sockets_list:
            sock.close()
        print("[*] Server safely terminated.")
        sys.exit(0)

if __name__ == "__main__":
    main()