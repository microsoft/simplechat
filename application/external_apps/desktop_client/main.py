"""
Main GUI Application for SimpleChat Desktop Client
Built with tkinter for cross-platform compatibility
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import threading
import json
from datetime import datetime
from typing import Optional, Dict, Any, List

from auth_manager import AuthenticationManager
from api_client import SimpleChat_API
from config import WINDOW_WIDTH, WINDOW_HEIGHT, WINDOW_TITLE


class SimpleChatGUI:
    """Main GUI application class"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.auth_manager = AuthenticationManager()
        self.api_client = SimpleChat_API(self.auth_manager)
        
        self.current_conversation_id = None
        self.conversations = []
        self.documents = []
        self.prompts = []
        
        self.setup_gui()
        self.setup_styles()
    
    def setup_gui(self):
        """Setup the main GUI layout"""
        self.root.title(WINDOW_TITLE)
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Create main container
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create notebook for tabs
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Create tabs
        self.create_auth_tab()
        self.create_chat_tab()
        self.create_documents_tab()
        self.create_prompts_tab()
        self.create_settings_tab()
        
        # Status bar
        self.status_bar = ttk.Label(main_frame, text="Not authenticated", relief=tk.SUNKEN)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))
        
        # Start with authentication tab
        self.notebook.select(0)
    
    def setup_styles(self):
        """Setup custom styles for the application"""
        style = ttk.Style()
        
        # Configure button styles
        style.configure('Success.TButton', background='lightgreen')
        style.configure('Danger.TButton', background='lightcoral')
        style.configure('Primary.TButton', background='lightblue')
    
    def create_auth_tab(self):
        """Create authentication tab"""
        auth_frame = ttk.Frame(self.notebook)
        self.notebook.add(auth_frame, text="Authentication")
        
        # Title
        title_label = ttk.Label(auth_frame, text="SimpleChat Desktop Client", 
                               font=('Arial', 16, 'bold'))
        title_label.pack(pady=20)
        
        # User info frame
        self.user_info_frame = ttk.LabelFrame(auth_frame, text="User Information")
        self.user_info_frame.pack(fill=tk.X, padx=20, pady=10)
        
        self.user_info_label = ttk.Label(self.user_info_frame, text="Not logged in")
        self.user_info_label.pack(pady=10)
        
        # Authentication buttons
        auth_buttons_frame = ttk.Frame(auth_frame)
        auth_buttons_frame.pack(pady=20)
        
        self.login_button = ttk.Button(auth_buttons_frame, text="Login with Azure AD", 
                                      command=self.login, style='Primary.TButton')
        self.login_button.pack(side=tk.LEFT, padx=10)
        
        self.logout_button = ttk.Button(auth_buttons_frame, text="Logout", 
                                       command=self.logout, style='Danger.TButton', 
                                       state=tk.DISABLED)
        self.logout_button.pack(side=tk.LEFT, padx=10)
        
        # API Status
        self.api_status_frame = ttk.LabelFrame(auth_frame, text="API Status")
        self.api_status_frame.pack(fill=tk.X, padx=20, pady=10)
        
        self.api_status_label = ttk.Label(self.api_status_frame, text="Not connected")
        self.api_status_label.pack(pady=5)
        
        self.test_api_button = ttk.Button(self.api_status_frame, text="Test API Connection", 
                                         command=self.test_api_connection)
        self.test_api_button.pack(pady=5)
    
    def create_chat_tab(self):
        """Create chat interface tab"""
        chat_frame = ttk.Frame(self.notebook)
        self.notebook.add(chat_frame, text="Chat")
        
        # Chat display area
        self.chat_display = scrolledtext.ScrolledText(chat_frame, height=20, state=tk.DISABLED)
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Message input frame
        input_frame = ttk.Frame(chat_frame)
        input_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        self.message_entry = ttk.Entry(input_frame)
        self.message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.message_entry.bind("<Return>", lambda e: self.send_message())
        
        self.send_button = ttk.Button(input_frame, text="Send", command=self.send_message, 
                                     style='Success.TButton')
        self.send_button.pack(side=tk.RIGHT)
        
        # Conversation controls
        conv_frame = ttk.Frame(chat_frame)
        conv_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(conv_frame, text="New Conversation", 
                  command=self.new_conversation).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(conv_frame, text="Load Conversations", 
                  command=self.load_conversations).pack(side=tk.LEFT, padx=5)
        
        # Conversation list
        self.conversation_listbox = tk.Listbox(conv_frame, height=3)
        self.conversation_listbox.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
        self.conversation_listbox.bind("<Double-Button-1>", self.load_conversation)
    
    def create_documents_tab(self):
        """Create documents management tab"""
        docs_frame = ttk.Frame(self.notebook)
        self.notebook.add(docs_frame, text="Documents")
        
        # Documents list
        docs_list_frame = ttk.LabelFrame(docs_frame, text="Documents")
        docs_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Documents listbox with scrollbar
        docs_scroll_frame = ttk.Frame(docs_list_frame)
        docs_scroll_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.docs_listbox = tk.Listbox(docs_scroll_frame)
        docs_scrollbar = ttk.Scrollbar(docs_scroll_frame, orient=tk.VERTICAL, 
                                      command=self.docs_listbox.yview)
        self.docs_listbox.configure(yscrollcommand=docs_scrollbar.set)
        
        self.docs_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        docs_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Documents controls
        docs_controls_frame = ttk.Frame(docs_frame)
        docs_controls_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(docs_controls_frame, text="Upload Document", 
                  command=self.upload_document, style='Primary.TButton').pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(docs_controls_frame, text="Refresh List", 
                  command=self.load_documents).pack(side=tk.LEFT, padx=5)
        ttk.Button(docs_controls_frame, text="Delete Selected", 
                  command=self.delete_document, style='Danger.TButton').pack(side=tk.LEFT, padx=5)
    
    def create_prompts_tab(self):
        """Create prompts management tab"""
        prompts_frame = ttk.Frame(self.notebook)
        self.notebook.add(prompts_frame, text="Prompts")
        
        # Prompts list
        prompts_list_frame = ttk.LabelFrame(prompts_frame, text="Prompts")
        prompts_list_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.prompts_listbox = tk.Listbox(prompts_list_frame, height=8)
        self.prompts_listbox.pack(fill=tk.X, padx=5, pady=5)
        self.prompts_listbox.bind("<Double-Button-1>", self.edit_prompt)
        
        # Prompt editor
        editor_frame = ttk.LabelFrame(prompts_frame, text="Prompt Editor")
        editor_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Title entry
        title_frame = ttk.Frame(editor_frame)
        title_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(title_frame, text="Title:").pack(side=tk.LEFT)
        self.prompt_title_entry = ttk.Entry(title_frame)
        self.prompt_title_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Content editor
        ttk.Label(editor_frame, text="Content:").pack(anchor=tk.W, padx=5)
        self.prompt_content_text = scrolledtext.ScrolledText(editor_frame, height=10)
        self.prompt_content_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Prompt controls
        prompts_controls_frame = ttk.Frame(prompts_frame)
        prompts_controls_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(prompts_controls_frame, text="New Prompt", 
                  command=self.new_prompt).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(prompts_controls_frame, text="Save Prompt", 
                  command=self.save_prompt, style='Success.TButton').pack(side=tk.LEFT, padx=5)
        ttk.Button(prompts_controls_frame, text="Load Prompts", 
                  command=self.load_prompts).pack(side=tk.LEFT, padx=5)
        ttk.Button(prompts_controls_frame, text="Delete Selected", 
                  command=self.delete_prompt, style='Danger.TButton').pack(side=tk.LEFT, padx=5)
        
        self.current_prompt_id = None
    
    def create_settings_tab(self):
        """Create settings tab"""
        settings_frame = ttk.Frame(self.notebook)
        self.notebook.add(settings_frame, text="Settings")
        
        # Connection settings
        conn_frame = ttk.LabelFrame(settings_frame, text="Connection Settings")
        conn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(conn_frame, text="API Base URL:").pack(anchor=tk.W, padx=5, pady=2)
        self.api_url_entry = ttk.Entry(conn_frame)
        self.api_url_entry.pack(fill=tk.X, padx=5, pady=2)
        self.api_url_entry.insert(0, self.api_client.base_url)
        
        # Application info
        info_frame = ttk.LabelFrame(settings_frame, text="Application Information")
        info_frame.pack(fill=tk.X, padx=10, pady=10)
        
        info_text = """
SimpleChat Desktop Client v1.0
Built with tkinter and Python

Features:
- Azure AD Authentication
- Session-based API communication
- Chat interface
- Document management
- Prompt management
- Cross-platform compatibility
        """
        
        ttk.Label(info_frame, text=info_text.strip(), justify=tk.LEFT).pack(padx=10, pady=10)
    
    # Authentication Methods
    def login(self):
        """Handle user login"""
        self.status_bar.config(text="Authenticating...")
        self.login_button.config(state=tk.DISABLED)
        
        def login_thread():
            try:
                success = self.auth_manager.login()
                
                # Update UI in main thread
                self.root.after(0, lambda: self.on_login_complete(success))
                
            except Exception as e:
                self.root.after(0, lambda: self.on_login_error(str(e)))
        
        # Run login in separate thread to prevent UI freezing
        threading.Thread(target=login_thread, daemon=True).start()
    
    def on_login_complete(self, success: bool):
        """Handle login completion"""
        if success:
            user_info = self.auth_manager.get_user_info()
            user_name = user_info.get('name', 'Unknown') if user_info else 'Unknown'
            
            self.user_info_label.config(text=f"Logged in as: {user_name}")
            self.status_bar.config(text=f"Authenticated as {user_name}")
            
            self.login_button.config(state=tk.DISABLED)
            self.logout_button.config(state=tk.NORMAL)
            
            # Enable tabs
            for i in range(1, self.notebook.index("end")):
                self.notebook.tab(i, state="normal")
            
            messagebox.showinfo("Success", f"Successfully logged in as {user_name}")
            
            # Load initial data
            self.load_conversations()
            self.load_documents()
            self.load_prompts()
        else:
            messagebox.showerror("Error", "Authentication failed. Please try again.")
            self.status_bar.config(text="Authentication failed")
            self.login_button.config(state=tk.NORMAL)
    
    def on_login_error(self, error_message: str):
        """Handle login error"""
        messagebox.showerror("Login Error", f"Login failed: {error_message}")
        self.status_bar.config(text="Authentication error")
        self.login_button.config(state=tk.NORMAL)
    
    def logout(self):
        """Handle user logout"""
        if messagebox.askyesno("Confirm Logout", "Are you sure you want to logout?"):
            self.auth_manager.logout()
            
            self.user_info_label.config(text="Not logged in")
            self.status_bar.config(text="Not authenticated")
            
            self.login_button.config(state=tk.NORMAL)
            self.logout_button.config(state=tk.DISABLED)
            
            # Disable tabs except authentication
            for i in range(1, self.notebook.index("end")):
                self.notebook.tab(i, state="disabled")
            
            # Clear data
            self.clear_all_data()
            
            # Switch to authentication tab
            self.notebook.select(0)
    
    def test_api_connection(self):
        """Test API connection"""
        try:
            if not self.auth_manager.is_authenticated():
                messagebox.showwarning("Warning", "Please login first to test API connection")
                return
            
            # Show progress
            self.api_status_label.config(text="Testing API connection...")
            self.root.update()
            
            # Use the improved test connection method
            result = self.api_client.test_connection()
            
            if result['success']:
                self.api_status_label.config(text="API connection successful")
                
                # Show detailed success message
                message = f"{result['message']}\n\n{result['details']}"
                if result['endpoints']:
                    message += "\n\nEndpoint Status:"
                    for endpoint, data in result['endpoints'].items():
                        status = "✓" if data.get('accessible', False) else "✗"
                        message += f"\n{status} {endpoint}: {data.get('status', 'unknown')}"
                
                messagebox.showinfo("API Test Success", message)
            else:
                self.api_status_label.config(text="API connection failed")
                
                # Show detailed error message
                message = f"{result['message']}\n\n{result['details']}"
                if result['endpoints']:
                    message += "\n\nEndpoint Status:"
                    for endpoint, data in result['endpoints'].items():
                        status = "✓" if data.get('accessible', False) else "✗"
                        error_info = data.get('error', data.get('status', 'unknown'))
                        message += f"\n{status} {endpoint}: {error_info}"
                
                messagebox.showerror("API Test Failed", message)
                
        except Exception as e:
            self.api_status_label.config(text="API test error")
            messagebox.showerror("Error", f"API test failed with exception: {str(e)}")
    
    # Chat Methods
    def send_message(self):
        """Send chat message"""
        if not self.auth_manager.is_authenticated():
            messagebox.showwarning("Warning", "Please login first")
            return
        
        message = self.message_entry.get().strip()
        if not message:
            return
        
        # Clear input
        self.message_entry.delete(0, tk.END)
        
        # Add message to display
        self.add_message_to_display("You", message)
        
        def send_thread():
            try:
                response = self.api_client.send_message(
                    message=message,
                    conversation_id=self.current_conversation_id
                )
                
                # Update UI in main thread
                self.root.after(0, lambda: self.on_message_response(response))
                
            except Exception as e:
                self.root.after(0, lambda: self.on_message_error(str(e)))
        
        threading.Thread(target=send_thread, daemon=True).start()
    
    def on_message_response(self, response: Dict[str, Any]):
        """Handle chat response"""
        if 'response' in response:
            self.add_message_to_display("Assistant", response['response'])
        
        if 'conversation_id' in response:
            self.current_conversation_id = response['conversation_id']
    
    def on_message_error(self, error_message: str):
        """Handle chat error"""
        self.add_message_to_display("System", f"Error: {error_message}")
    
    def add_message_to_display(self, sender: str, message: str):
        """Add message to chat display"""
        self.chat_display.config(state=tk.NORMAL)
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.chat_display.insert(tk.END, f"[{timestamp}] {sender}: {message}\n\n")
        
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)
    
    def new_conversation(self):
        """Start new conversation"""
        self.current_conversation_id = None
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.delete(1.0, tk.END)
        self.chat_display.config(state=tk.DISABLED)
        self.add_message_to_display("System", "New conversation started")
    
    def load_conversations(self):
        """Load conversation list"""
        if not self.auth_manager.is_authenticated():
            return
        
        def load_thread():
            try:
                conversations = self.api_client.get_conversations()
                self.root.after(0, lambda: self.on_conversations_loaded(conversations))
            except Exception as e:
                self.root.after(0, lambda: print(f"Failed to load conversations: {e}"))
        
        threading.Thread(target=load_thread, daemon=True).start()
    
    def on_conversations_loaded(self, conversations: List[Dict[str, Any]]):
        """Handle loaded conversations"""
        self.conversations = conversations
        self.conversation_listbox.delete(0, tk.END)
        
        for conv in conversations:
            title = conv.get('title', f"Conversation {conv.get('id', 'Unknown')}")
            self.conversation_listbox.insert(tk.END, title)
    
    def load_conversation(self, event):
        """Load selected conversation"""
        selection = self.conversation_listbox.curselection()
        if selection:
            conv = self.conversations[selection[0]]
            self.current_conversation_id = conv.get('id')
            
            # Load conversation details if needed
            # For now, just switch to chat tab
            self.notebook.select(1)  # Chat tab
    
    # Document Methods
    def load_documents(self):
        """Load documents list"""
        if not self.auth_manager.is_authenticated():
            return
        
        def load_thread():
            try:
                documents = self.api_client.get_documents()
                self.root.after(0, lambda: self.on_documents_loaded(documents))
            except Exception as e:
                self.root.after(0, lambda: print(f"Failed to load documents: {e}"))
        
        threading.Thread(target=load_thread, daemon=True).start()
    
    def on_documents_loaded(self, documents: List[Dict[str, Any]]):
        """Handle loaded documents"""
        self.documents = documents
        self.docs_listbox.delete(0, tk.END)
        
        for doc in documents:
            title = doc.get('title', doc.get('filename', 'Unknown Document'))
            self.docs_listbox.insert(tk.END, title)
    
    def upload_document(self):
        """Upload document"""
        if not self.auth_manager.is_authenticated():
            messagebox.showwarning("Warning", "Please login first")
            return
        
        file_path = filedialog.askopenfilename(
            title="Select Document",
            filetypes=[
                ("All Files", "*.*"),
                ("PDF Files", "*.pdf"),
                ("Word Documents", "*.docx"),
                ("Text Files", "*.txt")
            ]
        )
        
        if file_path:
            def upload_thread():
                try:
                    result = self.api_client.upload_document(file_path)
                    self.root.after(0, lambda: self.on_document_uploaded(result))
                except Exception as e:
                    self.root.after(0, lambda: self.on_document_upload_error(str(e)))
            
            threading.Thread(target=upload_thread, daemon=True).start()
    
    def on_document_uploaded(self, result: Dict[str, Any]):
        """Handle document upload success"""
        messagebox.showinfo("Success", "Document uploaded successfully!")
        self.load_documents()  # Refresh list
    
    def on_document_upload_error(self, error_message: str):
        """Handle document upload error"""
        messagebox.showerror("Upload Error", f"Failed to upload document: {error_message}")
    
    def delete_document(self):
        """Delete selected document"""
        selection = self.docs_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a document to delete")
            return
        
        if not self.auth_manager.is_authenticated():
            messagebox.showwarning("Warning", "Please login first")
            return
        
        doc = self.documents[selection[0]]
        doc_title = doc.get('title', doc.get('filename', 'Unknown Document'))
        
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete '{doc_title}'?"):
            def delete_thread():
                try:
                    self.api_client.delete_document(doc['id'])
                    self.root.after(0, lambda: self.on_document_deleted())
                except Exception as e:
                    self.root.after(0, lambda: self.on_document_delete_error(str(e)))
            
            threading.Thread(target=delete_thread, daemon=True).start()
    
    def on_document_deleted(self):
        """Handle document deletion success"""
        messagebox.showinfo("Success", "Document deleted successfully!")
        self.load_documents()  # Refresh list
    
    def on_document_delete_error(self, error_message: str):
        """Handle document deletion error"""
        messagebox.showerror("Delete Error", f"Failed to delete document: {error_message}")
    
    # Prompt Methods
    def load_prompts(self):
        """Load prompts list"""
        if not self.auth_manager.is_authenticated():
            return
        
        def load_thread():
            try:
                prompts = self.api_client.get_prompts()
                self.root.after(0, lambda: self.on_prompts_loaded(prompts))
            except Exception as e:
                self.root.after(0, lambda: print(f"Failed to load prompts: {e}"))
        
        threading.Thread(target=load_thread, daemon=True).start()
    
    def on_prompts_loaded(self, prompts: List[Dict[str, Any]]):
        """Handle loaded prompts"""
        self.prompts = prompts
        self.prompts_listbox.delete(0, tk.END)
        
        for prompt in prompts:
            title = prompt.get('title', 'Untitled Prompt')
            self.prompts_listbox.insert(tk.END, title)
    
    def new_prompt(self):
        """Create new prompt"""
        self.current_prompt_id = None
        self.prompt_title_entry.delete(0, tk.END)
        self.prompt_content_text.delete(1.0, tk.END)
    
    def edit_prompt(self, event):
        """Edit selected prompt"""
        selection = self.prompts_listbox.curselection()
        if selection:
            prompt = self.prompts[selection[0]]
            self.current_prompt_id = prompt.get('id')
            
            self.prompt_title_entry.delete(0, tk.END)
            self.prompt_title_entry.insert(0, prompt.get('title', ''))
            
            self.prompt_content_text.delete(1.0, tk.END)
            self.prompt_content_text.insert(1.0, prompt.get('content', ''))
    
    def save_prompt(self):
        """Save current prompt"""
        if not self.auth_manager.is_authenticated():
            messagebox.showwarning("Warning", "Please login first")
            return
        
        title = self.prompt_title_entry.get().strip()
        content = self.prompt_content_text.get(1.0, tk.END).strip()
        
        if not title or not content:
            messagebox.showwarning("Warning", "Please enter both title and content")
            return
        
        def save_thread():
            try:
                if self.current_prompt_id:
                    # Update existing prompt
                    result = self.api_client.update_prompt(
                        self.current_prompt_id, title=title, content=content
                    )
                else:
                    # Create new prompt
                    result = self.api_client.create_prompt(title=title, content=content)
                
                self.root.after(0, lambda: self.on_prompt_saved(result))
            except Exception as e:
                self.root.after(0, lambda: self.on_prompt_save_error(str(e)))
        
        threading.Thread(target=save_thread, daemon=True).start()
    
    def on_prompt_saved(self, result: Dict[str, Any]):
        """Handle prompt save success"""
        messagebox.showinfo("Success", "Prompt saved successfully!")
        self.load_prompts()  # Refresh list
    
    def on_prompt_save_error(self, error_message: str):
        """Handle prompt save error"""
        messagebox.showerror("Save Error", f"Failed to save prompt: {error_message}")
    
    def delete_prompt(self):
        """Delete selected prompt"""
        selection = self.prompts_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a prompt to delete")
            return
        
        if not self.auth_manager.is_authenticated():
            messagebox.showwarning("Warning", "Please login first")
            return
        
        prompt = self.prompts[selection[0]]
        prompt_title = prompt.get('title', 'Untitled Prompt')
        
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete '{prompt_title}'?"):
            def delete_thread():
                try:
                    self.api_client.delete_prompt(prompt['id'])
                    self.root.after(0, lambda: self.on_prompt_deleted())
                except Exception as e:
                    self.root.after(0, lambda: self.on_prompt_delete_error(str(e)))
            
            threading.Thread(target=delete_thread, daemon=True).start()
    
    def on_prompt_deleted(self):
        """Handle prompt deletion success"""
        messagebox.showinfo("Success", "Prompt deleted successfully!")
        self.load_prompts()  # Refresh list
        self.new_prompt()  # Clear editor
    
    def on_prompt_delete_error(self, error_message: str):
        """Handle prompt deletion error"""
        messagebox.showerror("Delete Error", f"Failed to delete prompt: {error_message}")
    
    # Utility Methods
    def clear_all_data(self):
        """Clear all loaded data"""
        self.conversations = []
        self.documents = []
        self.prompts = []
        self.current_conversation_id = None
        self.current_prompt_id = None
        
        # Clear UI elements
        self.conversation_listbox.delete(0, tk.END)
        self.docs_listbox.delete(0, tk.END)
        self.prompts_listbox.delete(0, tk.END)
        
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.delete(1.0, tk.END)
        self.chat_display.config(state=tk.DISABLED)
        
        self.prompt_title_entry.delete(0, tk.END)
        self.prompt_content_text.delete(1.0, tk.END)
    
    def on_closing(self):
        """Handle application closing"""
        if self.auth_manager.is_authenticated():
            if messagebox.askyesno("Quit", "Do you want to logout before closing?"):
                self.auth_manager.logout()
        
        self.root.destroy()
    
    def run(self):
        """Start the GUI application"""
        # Disable all tabs except authentication initially
        for i in range(1, self.notebook.index("end")):
            self.notebook.tab(i, state="disabled")
        
        self.root.mainloop()


def main():
    """Main application entry point"""
    try:
        app = SimpleChatGUI()
        app.run()
    except Exception as e:
        print(f"Application error: {e}")
        messagebox.showerror("Application Error", f"Failed to start application: {e}")


if __name__ == "__main__":
    main()
