# NYX - Terminal-Native Secure Communication

NYX is a secure, terminal-native distributed communication protocol with end-to-end encryption. This implementation provides both a PHP relay server and a Python client for secure messaging.

## Project Structure

```
NYX/
├── server/              # PHP Relay Server (unchanged)
│   ├── index.php       # Router
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
├── client/             # Python Client (refactored)
│   ├── main.py         # Entry point & application logic
│   ├── config.py       # Configuration management (~/.nyx/config.json)
│   ├── crypto.py       # X25519 + Ed25519 + ChaCha20-Poly1305
│   ├── db.py           # Local SQLite storage
│   ├── commands.py     # Command handlers
│   ├── ui.py           # REPL interface
│   └── requirements.txt
├── Dockerfile          # Server container config
└── railway.json        # Railway deployment config
```

## Features

### Server (PHP)
- RESTful API for message relay
- SQLite/MySQL database support
- Health checks and session management
- Message queuing and delivery
- Key exchange support

### Client (Python)
- **End-to-End Encryption**: X25519 key exchange + ChaCha20-Poly1305 AEAD
- **Identity Management**: Ed25519-based identities with Bech32 encoding (nyx1...)
- **Local Storage**: SQLite database for messages and contacts
- **Interactive REPL**: Simple command-line interface
- **Configuration**: XDG-compliant config in ~/.nyx/

## Installation

### Prerequisites
- Python 3.11+ (for client)
- PHP 8.0+ with PDO (for server)
- SQLite3 or MySQL (for server database)

### Client Setup

1. Clone the repository:
```bash
git clone https://github.com/openclaw02221/NYX.git
cd NYX/client
```

2. Create a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Run the client:
```bash
python main.py
```

### Server Setup

1. Navigate to the server directory:
```bash
cd NYX/server
```

2. Configure your database in `db.php`

3. Deploy using Docker:
```bash
docker build -t nyx-server .
docker run -p 8080:80 nyx-server
```

Or use PHP's built-in server for development:
```bash
php -S localhost:8080 -t server/
```

## Usage

### Client Commands

The client runs an interactive REPL. Available commands:

```
/help              - Show all commands
/status            - Show connection and identity status
/identity          - Display your identity
/contacts          - List all contacts
/add <id> [name]   - Add a contact
/dm <id> [msg]     - Send/view direct messages
/conversations     - List all conversations
/sync              - Sync messages from server
/exit              - Exit the client
```

### First Run

On first run, the client will:
1. Create a new identity (nyx1... address)
2. Generate a 24-word recovery phrase
3. Initialize the local database at ~/.local/share/nyx/

**Important**: Save your recovery phrase securely. It's the only way to recover your identity if you lose access.

### Configuration

The client uses `~/.nyx/config.json` for configuration:

```json
{
  "network": {
    "default_server": "https://nyx-relay.railway.app",
    "connection_timeout": 10,
    "max_retries": 3
  },
  "storage": {
    "data_dir": "",
    "db_filename": "nyx.db"
  }
}
```

You can override settings via command line:
```bash
python main.py --server https://my-server.com --data-dir /custom/path
```

## Architecture

### Cryptographic Primitives
- **Identity Keys**: Ed25519 for signatures and identity
- **Key Exchange**: X25519 Diffie-Hellman
- **AEAD**: ChaCha20-Poly1305 for message encryption
- **Encoding**: Bech32 for human-readable identities

### Client Architecture
```
┌─────────────────────────────────────────┐
│            main.py (Entry)              │
├─────────────────────────────────────────┤
│         ui.py (REPL Interface)          │
├─────────────────────────────────────────┤
│      commands.py (Command Handlers)     │
├─────────────────────────────────────────┤
│  crypto.py  │  db.py  │  config.py     │
│  (E2EE)     │ (Storage) │ (Settings)    │
└─────────────────────────────────────────┘
```

### Server API Endpoints
- `GET /api/health` - Server health check
- `POST /api/session` - Session management
- `POST /api/messages` - Send/receive messages
- `GET /api/keys/:identity` - Fetch public keys
- `GET /api/discovery` - Discover other users
- `GET /api/profile/:identity` - Get user profile

## Development

### Running Tests
```bash
cd client
source venv/bin/activate
python -m pytest tests/  # (when tests are added)
```

### Code Style
The project follows:
- Python: PEP 8 with 100-character lines
- PHP: PSR-12 coding standards

## Security Notes

1. **Private keys are stored unencrypted** in the local database for this MVP. Production deployments should use SQLCipher or application-level encryption.

2. **Recovery phrases** are generated but not yet fully integrated with key derivation. This is a placeholder for future BIP39 implementation.

3. **Server authentication** is not yet implemented. The relay server is trusted by default.

## Deployment

### Railway (Server)
The server is configured for one-click deployment to Railway:

```bash
railway up
```

### Docker (Server)
```bash
docker build -t nyx-server .
docker run -p 8080:80 -e DATABASE_URL=sqlite:///data/nyx.db nyx-server
```

## License

Open Source

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Roadmap

- [ ] Full BIP39 recovery implementation
- [ ] SQLCipher integration for encrypted local storage
- [ ] Server authentication and certificate pinning
- [ ] Group messaging support
- [ ] File transfer capabilities
- [ ] Mobile clients (iOS/Android)
- [ ] Desktop GUI application

## Contact

For questions or issues, please open a GitHub issue.

---

**Note**: This is an MVP implementation focused on core functionality. Production deployments should implement additional security hardening, monitoring, and operational features.