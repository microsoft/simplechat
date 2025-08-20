# SimpleChat External Applications

This directory contains external applications and tools that interact with the SimpleChat Flask API backend.

## Available Applications

### Desktop Client (`desktop_client/`)
A cross-platform desktop application built with Python and tkinter that provides a graphical user interface for SimpleChat.

**Features:**
- Azure AD authentication with session management
- Real-time chat interface with conversation history
- Document upload and management
- Prompt creation and editing
- Cross-platform compatibility (Windows, macOS, Linux)

**Quick Start:**
```bash
cd desktop_client
python launcher.py
# or on Windows: run.bat
# or on Unix: ./run.sh
```

See `desktop_client/README.md` for detailed installation and usage instructions.

### MCP Server (`mcp_server/`)
Model Context Protocol server for SimpleChat API integration.

### MCP Client (`mcp_client/`)
Model Context Protocol client for testing and development.

### Database Seeder (`databaseseeder/`)
Tool for seeding the database with sample data.

### Bulk Loader (`bulkloader/`)
Utility for bulk loading data into SimpleChat.

## Development

Each application in this directory is self-contained with its own:
- Dependencies (`requirements.txt`)
- Configuration files (`.env` or similar)
- Documentation (`README.md`)
- Launcher scripts

## Getting Started

1. Choose the application you want to use
2. Navigate to its directory
3. Follow the installation instructions in its README
4. Configure the application for your SimpleChat backend
5. Run the application using the provided launcher scripts

## Support

For application-specific issues, refer to the README file in each application's directory. For general SimpleChat backend issues, refer to the main repository documentation.