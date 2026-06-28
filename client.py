# Import the sys module to interact with the Python interpreter and exit the script
import sys
# Import the subprocess module to execute terminal commands (used for pip install)
import subprocess
# Import importlib.util to check if third-party modules exist without crashing the script
import importlib.util
# Import the socket module for establishing TCP network connections
import socket
# Import the threading module to run background tasks (like receiving messages) concurrently
import threading
# Import the json module to serialize and deserialize communication payloads
import json
# Import the os module to clear the terminal screen and manage file paths
import os
# Import base64 to encode binary files into safe text for JSON transmission
import base64
# Import traceback for detailed error debugging and logging
import traceback

# Define a function to automatically verify and install required libraries
def check_requirements():
    # Define a set containing the names of the required third-party libraries
    required = {'colorama', 'prompt_toolkit'}
    # Initialize an empty list to store the names of missing libraries
    missing = []
    
    # Loop through each required library name
    for req in required:
        # Check if the module specification cannot be found in the current environment
        if importlib.util.find_spec(req) is None:
            # If it's missing, append it to the missing list
            missing.append(req)
            
    # If the missing list is not empty (at least one requirement is missing)
    if missing:
        # Print a warning displaying which modules are missing
        print(f"[*] Missing required modules: {', '.join(missing)}")
        # Ask the user if they want the script to install them automatically
        ans = input("[?] Would you like to install them automatically? (y/n): ")
        
        # Check if the user's answer is 'y' (ignoring case)
        if ans.lower() == 'y':
            # Start a try block in case the pip installation fails (e.g., no internet)
            try:
                # Print a status message indicating installation has started
                print("[*] Installing...")
                # Run the pip install command via subprocess using the current Python executable
                subprocess.check_call([sys.executable, '-m', 'pip', 'install', *missing])
                # Print a success message if installation completes without throwing an error
                print("[+] Modules installed successfully. Restarting...\n")
            # Catch any exception thrown by subprocess
            except Exception as e:
                # Print the error message
                print(f"[-] Auto-install failed: {e}")
                # Exit the script with an error code (1)
                sys.exit(1)
        # If the user answered anything other than 'y'
        else:
            # Print a message stating the program cannot run
            print("[-] Cannot continue without required modules. Exiting.")
            # Exit the script
            sys.exit(1)

# Call the requirement checker before trying to import any third-party modules
check_requirements()

# Import the colorama library to enable cross-platform colored terminal output
import colorama
# Extract the Fore (text color) and Style (text styling) classes from colorama
from colorama import Fore, Style
# Import prompt, print_formatted_text, and ANSI to fix Windows Terminal rendering issues
from prompt_toolkit import prompt, print_formatted_text, ANSI
# Import Completer and Completion base classes to build a custom, smart autocompleter
from prompt_toolkit.completion import Completer, Completion
# Import patch_stdout to prevent background prints from corrupting the active input line
from prompt_toolkit.patch_stdout import patch_stdout

# Initialize colorama and configure it to automatically reset the color after every print statement
colorama.init(autoreset=True)

# Define a custom print function to force prompt_toolkit to parse ANSI color codes natively
def cprint(text):
    # Print the formatted text using prompt_toolkit's ANSI parser to render colors correctly
    print_formatted_text(ANSI(str(text)))

# Define a list of available commands for the autocompleter
COMMANDS = ['/help', '/online', '/msg', '/file', '/accept', '/clear', '/exit']

# Global dictionary to track files we have offered to send (Key: filename, Value: path)
pending_uploads = {}

# Define a custom Completer class to precisely control when autocomplete triggers
class SmartCommandCompleter(Completer):
    # Override the built-in get_completions generator method
    def get_completions(self, document, complete_event):
        # Get the exact text the user has typed before the cursor
        text = document.text_before_cursor
        # Trigger autocomplete ONLY if there are no spaces AND it starts with a forward slash
        if ' ' not in text and text.startswith('/'):
            # Loop through all available commands defined in the COMMANDS list
            for cmd in COMMANDS:
                # Check if the command starts with the letters the user has typed so far
                if cmd.startswith(text.lower()):
                    # Yield a Completion object to suggest the full command
                    yield Completion(cmd, start_position=-len(text))

# Initialize our custom smart completer
command_completer = SmartCommandCompleter()

# Define a function to display the formatted help menu
def print_help():
    cprint(f"\n{Fore.CYAN}=== COMMAND MENU ==={Style.RESET_ALL}")
    cprint(f"{Fore.GREEN}[Texting]{Style.RESET_ALL}")
    cprint(f"  {Fore.YELLOW}<just type>{Style.RESET_ALL}      - Broadcast message to everyone")
    cprint(f"  {Fore.YELLOW}/msg [user] [txt]{Style.RESET_ALL}- Send a private message (user must be online)")
    cprint(f"{Fore.GREEN}[Files]{Style.RESET_ALL}")
    cprint(f"  {Fore.YELLOW}/file all [path]{Style.RESET_ALL} - Offer a file to everyone (Max 500KB)")
    cprint(f"  {Fore.YELLOW}/file [user] [path]{Style.RESET_ALL}- Offer a file to a specific user (Max 500KB)")
    cprint(f"  {Fore.YELLOW}/accept [user] [file]{Style.RESET_ALL} - Accept and download an offered file")
    cprint(f"{Fore.GREEN}[System]{Style.RESET_ALL}")
    cprint(f"  {Fore.YELLOW}/online{Style.RESET_ALL}          - Show list of connected users")
    cprint(f"  {Fore.YELLOW}/clear{Style.RESET_ALL}           - Clear the terminal screen")
    cprint(f"  {Fore.YELLOW}/help{Style.RESET_ALL}            - Show this menu")
    cprint(f"  {Fore.YELLOW}/exit{Style.RESET_ALL}            - Leave server and return to main menu\n")

# Define the background thread function to continuously receive network messages
def receive_messages(sock, disconnect_flag):
    # Initialize a local TCP stream buffer as RAW BYTES to prevent UnicodeDecodeError on split packets
    buffer = b""
    # Loop continuously as long as the disconnect flag is NOT set to True
    while not disconnect_flag.is_set():
        # Start a try block to handle network receiving errors
        try:
            # Receive up to 1MB of raw bytes from the server socket
            chunk = sock.recv(1048576)
            
            # If the received message is completely empty, the server has closed the connection
            if not chunk:
                # Check if the disconnection was NOT intentional
                if not disconnect_flag.is_set():
                    # Print an error message in red notifying the user
                    cprint(f"\n{Fore.RED}[-] Connection closed by the server. Press ENTER to return to menu.{Style.RESET_ALL}")
                    # Set the flag to true to signal the main thread
                    disconnect_flag.set()
                # Break out of the loop
                break
                
            # Append the newly received raw bytes to the continuous buffer
            buffer += chunk
            
            # Process while a complete framed packet (ending in a newline byte) exists in the buffer
            while b'\n' in buffer:
                # Split the byte buffer at the first newline byte
                raw_msg_bytes, buffer = buffer.split(b'\n', 1)
                
                # Ignore completely blank byte sequences
                if not raw_msg_bytes.strip():
                    continue
                    
                # Decode the safely isolated bytes into a UTF-8 string
                raw_msg = raw_msg_bytes.decode('utf-8')
                # Parse the complete JSON string into a dictionary
                data = json.loads(raw_msg)
                
                # Check if the parsed message is a standard user chat message
                if data['type'] == 'msg':
                    # Print the sender's name in blue, followed by their message content
                    cprint(f"{Fore.BLUE}[{data['sender']}]{Style.RESET_ALL}: {data['content']}")
                    
                # Check if the parsed message is a system notification from the server
                elif data['type'] == 'system':
                    # Check if the word "Error" exists in the system message string
                    if "Error" in data['msg']:
                        # If it's an error, print it in red
                        cprint(f"{Fore.RED}[SERVER ERROR]: {data['msg']}{Style.RESET_ALL}")
                    # If it's a normal system message
                    else:
                        # Print it in green
                        cprint(f"{Fore.GREEN}[SERVER]: {data['msg']}{Style.RESET_ALL}")
                        
                # Check if the parsed message is a file transfer handshake offer
                elif data['type'] == 'file_offer':
                    # Print a magenta alert displaying the sender, filename, and size
                    cprint(f"\n{Fore.MAGENTA}[!] User '{data['sender']}' wants to send a file: {data['filename']} ({data['size']} bytes){Style.RESET_ALL}")
                    # Provide instructions on how to accept the file without blocking the thread
                    cprint(f"{Fore.MAGENTA}[!] Type: /accept {data['sender']} {data['filename']}  to download it.{Style.RESET_ALL}\n")
                    
                # Check if a user accepted a file we offered to them
                elif data['type'] == 'file_accept':
                    # Extract the name of the user who accepted the file
                    accepter = data['sender']
                    # Extract the exact filename they requested
                    requested_file = data['filename']
                    
                    # Check if the requested file is still stored in our pending uploads dictionary
                    if requested_file in pending_uploads:
                        # Retrieve the absolute file path from the dictionary
                        filepath = pending_uploads[requested_file]
                        # Start try block to handle file reading errors
                        try:
                            # Open the file in Read Binary mode
                            with open(filepath, "rb") as f:
                                # Encode the binary data to Base64, then decode to a safe UTF-8 string
                                b64_data = base64.b64encode(f.read()).decode('utf-8')
                            
                            # Construct the payload dictionary containing the massive Base64 string
                            transfer_data = {"type": "file_transfer", "target": accepter, "filename": requested_file, "data": b64_data}
                            # Send the payload using sendall to guarantee delivery, appending \n for framing
                            sock.sendall((json.dumps(transfer_data) + '\n').encode('utf-8'))
                            
                            # Print a success confirmation to our local terminal
                            cprint(f"\n{Fore.GREEN}[+] User '{accepter}' accepted! File '{requested_file}' transmitted successfully.{Style.RESET_ALL}")
                        # Catch file reading errors (e.g. file was moved or deleted)
                        except Exception as e:
                            # Print a detailed debug error message in red
                            cprint(f"\n{Fore.RED}[DEBUG] Error reading file '{requested_file}': {type(e).__name__} - {e}{Style.RESET_ALL}")
                    # If the file is no longer in our pending dictionary
                    else:
                        # Print an error stating the file is no longer available
                        cprint(f"\n{Fore.RED}[-] User '{accepter}' tried to accept '{requested_file}', but it is no longer pending.{Style.RESET_ALL}")

                # Check if the parsed message is an incoming file carrying Base64 data
                elif data['type'] == 'file_transfer':
                    # Extract the original filename
                    filename = data['filename']
                    # Extract the sender's name
                    sender = data['sender']
                    # Extract the Base64 encoded file string
                    file_data_b64 = data['data']
                    
                    # Create a secure save path combining the sender's name and original filename
                    save_path = f"received_{sender}_{filename}"
                    
                    # Start try block to catch saving permission errors
                    try:
                        # Open the target path in 'wb' (Write Binary) mode
                        with open(save_path, "wb") as f:
                            # Decode the Base64 string back into raw bytes and write them to disk
                            f.write(base64.b64decode(file_data_b64))

                        # Print a highly visible success notification displaying the save path
                        cprint(f"\n{Fore.MAGENTA}[+] Download complete! Saved to root directory as: {save_path}{Style.RESET_ALL}")
                        
                        # Generate an automated reply to confirm successful download
                        ack_content = f"[AUTO-REPLY] User successfully downloaded '{filename}'."
                        # Construct the private message payload for the auto-reply
                        ack_data = {"type": "private_msg", "target": sender, "content": ack_content}
                        # Send the auto-reply to the server
                        sock.sendall((json.dumps(ack_data) + '\n').encode('utf-8'))
                    # Catch OS errors (e.g., no write permissions)
                    except Exception as e:
                        # Print a detailed debug error message
                        cprint(f"\n{Fore.RED}[DEBUG] Error saving downloaded file: {type(e).__name__} - {e}{Style.RESET_ALL}")
                    
        # Catch unexpected thread crashes (e.g., lost network, malformed JSON)
        except Exception as e:
            # Check if the error was not an intentional exit
            if not disconnect_flag.is_set():
                # Print the fatal error trace for debugging
                cprint(f"\n{Fore.RED}[DEBUG FATAL] Receiver Thread crashed: {type(e).__name__} - {e}{Style.RESET_ALL}")
                # Print instructions to return to the menu
                cprint(f"{Fore.RED}[-] Press ENTER to return to menu.{Style.RESET_ALL}")
                # Set the flag to stop the main loop
                disconnect_flag.set()
            # Break the loop to end the background thread safely
            break

# Define the main logic function of the client application
def main():
    # Print the main application banner in cyan
    print(f"{Fore.CYAN}=== Universal Secure Chat Client ==={Style.RESET_ALL}")
    
    # Start the outermost loop, allowing the user to return to the connection menu after typing /exit
    while True:
        # Print a header for the connection profile phase
        print(f"\n{Fore.CYAN}--- Server Connection Profile ---{Style.RESET_ALL}")
        
        # Ask for the server IP, defaulting to 127.0.0.1 if the user just presses Enter
        target_ip = input("Enter server IP (default 127.0.0.1): ").strip() or '127.0.0.1'
        # Ask for the server PORT, defaulting to 5555 if empty
        target_port_str = input("Enter server PORT (default 5555): ").strip() or '5555'
        # Convert the port string to an integer
        target_port = int(target_port_str)
        # Ask for the cluster password, removing any extra whitespace
        server_pass = input("Enter cluster password (press Enter if none): ").strip()

        # Initialize a new TCP client socket for IPv4
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # Start a try block to attempt the physical network connection
        try:
            # Connect the socket to the specified IP and Port tuple
            client_socket.connect((target_ip, target_port))
            # Print a success message in green
            print(f"{Fore.GREEN}[+] Connected to target cluster.{Style.RESET_ALL}")
        # Catch connection errors (e.g., connection refused, timeout)
        except Exception as e:
            # Print the error message in red
            print(f"{Fore.RED}[-] Unable to connect - {e}. Try again.{Style.RESET_ALL}")
            # Use 'continue' to skip the rest of the loop and prompt for connection details again
            continue 
        
        # Initialize a boolean flag to track if user authentication is successful
        auth_success = False
        
        # Start the authentication loop, running until auth_success becomes True
        while not auth_success:
            # Ask the user if they want to login or register, convert to lowercase
            action = input("Type 'login' or 'register': ").strip().lower()
            
            # Check if the user typed a valid action
            if action in ['login', 'register']:
                username = input("Username: ").strip()
                password = input("Password: ").strip()
                
                # Construct the authentication JSON payload dictionary
                auth_data = {
                    "type": "auth",
                    "action": action,
                    "username": username,
                    "password": password,
                    "server_password": server_pass
                }
                
                # Start a try block to handle network transmission during auth
                try:
                    # Convert dict to JSON, append \n, encode to bytes, and sendall to guarantee delivery
                    client_socket.sendall((json.dumps(auth_data) + '\n').encode('utf-8'))
                    # Wait to receive the server's response
                    response = client_socket.recv(4096)
                    # Decode the response, strip the \n, and parse the JSON into a dictionary
                    res_data = json.loads(response.decode('utf-8').strip())
                    
                    # Check if the server's response status is 'ok'
                    if res_data['status'] == 'ok':
                        # Print the success message from the server in green
                        print(f"{Fore.GREEN}[SERVER]: {res_data['msg']}{Style.RESET_ALL}")
                        # If the action was 'login', authentication is complete
                        if action == 'login':
                            # Set the flag to True, which breaks the while loop
                            auth_success = True 
                    # If the server rejected the authentication
                    else:
                        # Print the error message in red
                        print(f"{Fore.RED}[SERVER ERROR]: {res_data['msg']}{Style.RESET_ALL}")
                # Catch network errors during the authentication phase
                except Exception as e:
                    # Print the network error in red
                    print(f"{Fore.RED}[-] Network error during auth: {e}{Style.RESET_ALL}")
                    break
            # If the user typed something other than login or register
            else:
                # Print an invalid command warning
                print("Invalid command. Please try again.")

        # If the auth loop ended but authentication was NOT successful (e.g. network crash)
        if not auth_success:
            # Close the current socket
            client_socket.close()
            # Use continue to go back to the very beginning (connection profile phase)
            continue

        # Create a threading Event object. This acts as a shared boolean flag across threads
        disconnect_flag = threading.Event()
        
        # Initialize a new Thread targetting the receive_messages function
        # Pass the socket and the disconnect_flag as arguments to the function
        recv_thread = threading.Thread(target=receive_messages, args=(client_socket, disconnect_flag))
        # Set the thread as a daemon, meaning it will automatically die if the main program exits
        recv_thread.daemon = True
        # Start executing the background thread
        recv_thread.start()
        
        # Print the chat startup banner with instructions
        print(f"\n{Fore.CYAN}--- Chat Started (type '/help' for commands. Press TAB to autocomplete!) ---{Style.RESET_ALL}")
        
        # Use patch_stdout context manager to ensure background prints do not corrupt the input prompt
        with patch_stdout():
            # Start the inner chat loop, running until the disconnect flag is triggered
            while not disconnect_flag.is_set():
                # Start a try block to handle manual keyboard interrupts
                try:
                    # Use prompt_toolkit to get user input, passing our custom smart completer
                    msg = prompt('You: ', completer=command_completer).strip()
                    
                    # If the user just pressed Enter (empty message) or the disconnect flag is set
                    if not msg or disconnect_flag.is_set():
                        # Skip this iteration of the loop
                        continue
                    
                    # Route the user's input based on commands
                    
                    # If the user typed the help command
                    if msg.lower() == '/help':
                        # Call the print_help function
                        print_help()
                        
                    # If the user typed the online check command
                    elif msg.lower() == '/online':
                        # Create a command payload dictionary
                        cmd_data = {"type": "cmd", "command": "online"}
                        # Send the JSON encoded command to the server, appending \n
                        client_socket.sendall((json.dumps(cmd_data) + '\n').encode('utf-8'))
                        
                    # If the user typed the clear screen command
                    elif msg.lower() == '/clear':
                        # Execute 'cls' on Windows (nt) or 'clear' on Linux/macOS
                        os.system('cls' if os.name == 'nt' else 'clear')
                        
                    # If the user wants to leave the server
                    elif msg.lower() in ['/exit', '/quit']:
                        # Print a notification in yellow using custom cprint
                        cprint(f"{Fore.YELLOW}[*] Disconnecting from server...{Style.RESET_ALL}")
                        # Set the disconnect flag to True, which tells the background thread to stop
                        disconnect_flag.set()
                        # Break the inner chat loop
                        break 
                        
                    # If the user is trying to send a private message
                    elif msg.startswith('/msg '):
                        # Split the string into exactly 3 parts: ['/msg', 'target_name', 'message content']
                        parts = msg.split(' ', 2)
                        # Check if all 3 parts exist
                        if len(parts) >= 3:
                            # Extract target name and content
                            target, content = parts[1], parts[2]
                            # Create the private message payload dictionary
                            chat_data = {"type": "private_msg", "target": target, "content": content}
                            # Send the JSON encoded payload to the server
                            client_socket.sendall((json.dumps(chat_data) + '\n').encode('utf-8'))
                            # Print a local echo indicating the message was sent privately
                            cprint(f"{Fore.YELLOW}(Private to {target}): {content}{Style.RESET_ALL}")
                        # If the command syntax was wrong
                        else:
                            # Print a usage hint in red
                            cprint(f"{Fore.RED}Usage: /msg [user] [text]{Style.RESET_ALL}")

                    # If the user is trying to accept a file offer
                    elif msg.startswith('/accept '):
                        # Split the command into exactly 3 parts
                        parts = msg.split(' ', 2)
                        # Ensure all arguments are provided
                        if len(parts) == 3:
                            # Extract the sender's username and the filename
                            target_sender, filename = parts[1], parts[2]
                            # Construct the file_accept payload
                            accept_data = {"type": "file_accept", "target": target_sender, "filename": filename}
                            # Send the acceptance securely to the server
                            client_socket.sendall((json.dumps(accept_data) + '\n').encode('utf-8'))
                            # Print a local confirmation message
                            cprint(f"{Fore.YELLOW}[*] Acceptance sent to '{target_sender}'. Downloading file...{Style.RESET_ALL}")
                        # If the command syntax was wrong
                        else:
                            # Print a usage hint
                            cprint(f"{Fore.RED}Usage: /accept [user] [filename]{Style.RESET_ALL}")

                    # If the user is trying to offer a file
                    elif msg.startswith('/file '):
                        # Split the string into exactly 3 parts
                        parts = msg.split(' ', 2)
                        # Ensure all 3 parts exist
                        if len(parts) == 3:
                            # Extract the target username and the local file path
                            target, filepath = parts[1], parts[2]
                            
                            # Check if the file actually exists on the hard drive
                            if os.path.exists(filepath):
                                # Get the exact file size in bytes
                                filesize = os.path.getsize(filepath)
                                
                                # Enforce a 500KB limit to maintain JSON parsing stability in this academic project
                                if filesize > 500000:
                                    # Print an error warning the user about the size limit
                                    cprint(f"{Fore.RED}[-] File too large. Max size is 500KB for this academic lab.{Style.RESET_ALL}")
                                    # Skip the rest of this loop iteration to abort
                                    continue
                                
                                # Extract just the filename from the absolute path
                                filename = os.path.basename(filepath)
                                
                                # Save the filepath to our global dictionary so we can read it later if the user accepts
                                pending_uploads[filename] = filepath
                                
                                # Create the file offer metadata payload
                                offer = {"type": "file_offer", "target": target, "filename": filename, "size": filesize}
                                # Send the offer to the server
                                client_socket.sendall((json.dumps(offer) + '\n').encode('utf-8'))
                                
                                # Print a confirmation that the offer was sent
                                cprint(f"{Fore.GREEN}[+] File offer for '{filename}' sent to {target}. Waiting for them to /accept...{Style.RESET_ALL}")
                            # If the file path is invalid
                            else:
                                # Print an error message in red
                                cprint(f"{Fore.RED}[-] File not found on local disk.{Style.RESET_ALL}")
                        # If the command syntax was wrong
                        else:
                            # Print a usage hint
                            cprint(f"{Fore.RED}Usage: /file [user/all] [path]{Style.RESET_ALL}")
                            
                    # If the user typed a slash but it's an unrecognized command
                    elif msg.startswith('/'):
                        # Print an unknown command warning
                        cprint(f"{Fore.RED}Unknown command. Type /help{Style.RESET_ALL}")
                            
                    # If the input is not a command, treat it as a standard public chat message
                    else:
                        # Create the broadcast payload dictionary
                        chat_data = {"type": "broadcast", "content": msg}
                        # Send the JSON encoded payload to the server
                        client_socket.sendall((json.dumps(chat_data) + '\n').encode('utf-8'))
                        # Note: Local echo is handled implicitly because prompt_toolkit leaves 'You: msg' on screen
                        
                # Catch a CTRL+C keyboard interrupt during the chat phase
                except KeyboardInterrupt:
                    # Print a disconnection warning in red
                    cprint(f"\n{Fore.RED}Disconnecting via CTRL+C...{Style.RESET_ALL}")
                    # Set the disconnect flag to stop the background thread
                    disconnect_flag.set()
                    # Break the inner chat loop
                    break

        # After breaking out of the inner chat loop (either via /exit or CTRL+C)
        # Start a try block to safely close the socket
        try:
            # Explicitly close the socket connection
            client_socket.close()
        # Catch any errors (e.g., if the socket is already closed)
        except:
            # Ignore the error
            pass
            
        # Print a confirmation that the user has successfully left the server
        print(f"\n{Fore.GREEN}[+] Successfully left the server.{Style.RESET_ALL}")
        # The code will now loop back to the beginning of the 'while True' loop, 
        # showing "--- Server Connection Profile ---" again

# Standard idiom to check if the script is run directly
if __name__ == "__main__":
    # Wrap the entire main function execution in a try block
    try:
        # Execute the main program logic
        main()
    # Catch a global KeyboardInterrupt (if user presses CTRL+C at the connection menu)
    except KeyboardInterrupt:
        # Print a final termination message
        print(f"\n{Fore.RED}[*] Client terminated.{Style.RESET_ALL}")
        # Exit the application entirely with a success code (0)
        sys.exit(0)