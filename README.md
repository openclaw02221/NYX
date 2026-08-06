# NYX - Terminal-Native Secure Communication

NYX is a secure, terminal-native distributed communication protocol with end-to-end encryption. This implementation provides both a PHP relay server and a Python client for secure messaging.

**Version**: 0.0.5

## Project Structure

```
NYX/
├── server/              # PHP Relay Server
│   ├── index.php       # Entry point
│   ├── router.php      # Router for built-in server
│   ├── db.php          # PDO database connection
│   ├── helpers.php     # Shared utilities
│   ├── register.php    # Legacy registration endpoint
│   ├── send.php        # Legacy message send endpoint
│   ├── sync.php        # Legacy message sync endpoint
│   └── api/            # v3 API endpoints
│       ├── health.php
│       ├── session.php
│       ├── messages.php
│       ├── keys.php
│       ├── discovery.php
│       ├── profile.php
│       └── manifest.php
├── client/             # Python Client
│   ├── main.py         # Entry point
│   ├── config.py       # Configuration management
│   ├── crypto.py       # X25519 + Ed25519 + ChaCha20-Poly1305
│   ├── db.py           # Local SQLite storage
│   ├── commands.py     # Command handlers
│   ├── ui.py           # TUI and REPL interface
│   └── requirements.txt
├── Dockerfile          # Server container config
├── railway.json        # Railway deployment config
└── .gitignore          # Git exclusion rules
```

## Features

### Server (PHP)
- **RESTful API**: Clean API for message relay
- **Relay Mechanism**: Securely relay encrypted messages between clients
- **Health Checks**: Built-in monitoring endpoints
- **Flexible Deployment**: Supports Docker and Railway
- **Portability**: Uses PHP built-in server for easy setup

### Client (Python)
- **End-to-End Encryption**: X25519 key exchange + ChaCha20-Poly1305 AEAD
- **Identity Management**: Ed25519-based identities (nyx1...)
- **Dual UI**: Interactive REPL and rich TUI (Textual)
- **Local Storage**: SQLite database for persistent history
- **Asynchronous**: Non-blocking message synchronization

## Installation

### Prerequisites
- Python 3.11+
- PHP 8.1+
- SQLite3

### Client Setup

1. Clone the repository and navigate to `client/`:
```bash
git clone https://github.com/openclaw02221/NYX.git
cd NYX/client
```

2. Setup virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Run the client:
```bash
python main.py        # Starts TUI
python main.py --repl # Starts REPL
```

### Server Setup

1. Navigate to the server directory:
```bash
cd NYX/server
```

2. Run using PHP's built-in server:
```bash
php -S localhost:8000 router.php
```

3. Or deploy using Docker:
```bash
docker build -t nyx-server .
docker run -p 8000:8000 nyx-server
```

## Usage

### Client Commands (REPL/TUI)

```
/help              - Show all commands
/status            - Show connection and identity status
/identity          - Display your identity
/contacts          - List all contacts
/add <id> <name>   - Add a contact
/send <id> <msg>   - Send a message
/conversations     - List all conversations
/messages <id>     - View messages in a conversation
/sync              - Sync messages from server
/exit              - Exit the client
```

## Deployment

### Railway (Server)
Deploy the server to Railway using the provided `railway.json` and `Dockerfile`.

### Docker (Server)
```bash
docker build -t nyx-server .
docker run -p 8000:8000 -e PORT=8000 nyx-server
```

## Security
- All messages are encrypted locally before being sent to the relay server.
- Identities are cryptographic keys, ensuring authenticity.
- The relay server never sees unencrypted message content.

## License
Open Source