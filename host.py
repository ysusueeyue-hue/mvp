import os
import asyncio
import sqlite3
import threading
import time
import subprocess
import psutil
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import logging
import sys
import signal
import atexit

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot Configuration
BOT_TOKEN = "8424706293:AAGCdVoE0qa9wwt5E-J7ORerAuZ_4peSlI0"
ADMIN_ID = 8275890305  # Your admin ID
CHANNEL_ID = -1003200081005  # Your channel ID for file storage

# Auto-install required packages
def install_requirements():
    required_packages = [
        'python-telegram-bot==20.7',
        'psutil',
        'requests'
    ]
    
    for package in required_packages:
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
            logger.info(f"Successfully installed {package}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install {package}: {e}")

# Install requirements on startup
install_requirements()

# Database setup with schema migration
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
    # Create table if not exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS hostings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_name TEXT,
            file_path TEXT,
            file_id TEXT,
            start_time TEXT,
            last_restart TEXT,
            status TEXT DEFAULT 'running',
            process_id TEXT,
            restart_count INTEGER DEFAULT 0,
            total_uptime INTEGER DEFAULT 0,
            cpu_usage REAL DEFAULT 0,
            memory_usage REAL DEFAULT 0,
            data_sent INTEGER DEFAULT 0,
            data_received INTEGER DEFAULT 0,
            requirements_installed BOOLEAN DEFAULT FALSE
        )
    ''')
    
    # Users table for coins and bans
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            coins INTEGER DEFAULT 1,
            is_banned BOOLEAN DEFAULT FALSE,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            join_date TEXT,
            total_hosted INTEGER DEFAULT 0
        )
    ''')
    
    # Referrals table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            reward_claimed BOOLEAN DEFAULT FALSE,
            join_date TEXT
        )
    ''')
    
    # File storage table for channel
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS file_storage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_name TEXT,
            file_id TEXT,
            channel_message_id INTEGER,
            upload_time TEXT,
            file_size INTEGER
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialization completed")

init_db()

class UserManager:
    def __init__(self):
        pass
    
    def get_user(self, user_id):
        """Get user information"""
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return {
                'user_id': user[0],
                'username': user[1],
                'first_name': user[2],
                'last_name': user[3],
                'coins': user[4],
                'is_banned': bool(user[5]),
                'referred_by': user[6],
                'referral_count': user[7],
                'join_date': user[8],
                'total_hosted': user[9]
            }
        return None
    
    def create_user(self, user_id, username, first_name, last_name, referred_by=None):
        """Create new user with welcome bonus"""
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        try:
            # Check if user already exists
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            existing_user = cursor.fetchone()
            
            if existing_user:
                return False  # User already exists
            
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, last_name, coins, referred_by, join_date)
                VALUES (?, ?, ?, ?, 1, ?, ?)
            ''', (user_id, username, first_name, last_name, referred_by, datetime.now().isoformat()))
            
            # If referred by someone, give referral bonus
            if referred_by:
                # Give coin to referrer
                cursor.execute('UPDATE users SET coins = coins + 1, referral_count = referral_count + 1 WHERE user_id = ?', (referred_by,))
                
                # Record referral
                cursor.execute('''
                    INSERT INTO referrals (referrer_id, referred_id, join_date)
                    VALUES (?, ?, ?)
                ''', (referred_by, user_id, datetime.now().isoformat()))
            
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # User already exists
            return False
        finally:
            conn.close()
    
    def update_coins(self, user_id, coins):
        """Update user coins"""
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET coins = coins + ? WHERE user_id = ?', (coins, user_id))
        conn.commit()
        conn.close()
    
    def get_coins(self, user_id):
        """Get user coins"""
        user = self.get_user(user_id)
        return user['coins'] if user else 0
    
    def ban_user(self, user_id):
        """Ban user"""
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_banned = TRUE WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
    
    def unban_user(self, user_id):
        """Unban user"""
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_banned = FALSE WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
    
    def is_banned(self, user_id):
        """Check if user is banned"""
        user = self.get_user(user_id)
        return user['is_banned'] if user else False
    
    def get_all_users(self):
        """Get all users"""
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users')
        users = cursor.fetchall()
        conn.close()
        
        user_list = []
        for user in users:
            user_list.append({
                'user_id': user[0],
                'username': user[1],
                'first_name': user[2],
                'last_name': user[3],
                'coins': user[4],
                'is_banned': bool(user[5]),
                'referred_by': user[6],
                'referral_count': user[7],
                'join_date': user[8],
                'total_hosted': user[9]
            })
        return user_list
    
    def increment_hosted_count(self, user_id):
        """Increment user's hosted file count"""
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET total_hosted = total_hosted + 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

class FileStorageManager:
    def __init__(self):
        pass
    
    async def store_file_in_channel(self, context, user_id, file_name, file_path, file_size):
        """Store file in channel and return message ID"""
        try:
            with open(file_path, 'rb') as file:
                message = await context.bot.send_document(
                    chat_id=CHANNEL_ID,
                    document=file,
                    caption=f"📁 File: {file_name}\n👤 User ID: {user_id}\n📅 Uploaded: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    parse_mode='Markdown'
                )
            
            # Save to database
            conn = sqlite3.connect('bot_data.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO file_storage (user_id, file_name, file_id, channel_message_id, upload_time, file_size)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, file_name, str(message.document.file_id), message.message_id, datetime.now().isoformat(), file_size))
            conn.commit()
            conn.close()
            
            return message.message_id
        except Exception as e:
            logger.error(f"Error storing file in channel: {e}")
            return None
    
    def get_file_from_channel(self, file_id):
        """Get file info from database"""
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM file_storage WHERE file_id = ?', (file_id,))
        file_info = cursor.fetchone()
        conn.close()
        
        if file_info:
            return {
                'id': file_info[0],
                'user_id': file_info[1],
                'file_name': file_info[2],
                'file_id': file_info[3],
                'channel_message_id': file_info[4],
                'upload_time': file_info[5],
                'file_size': file_info[6]
            }
        return None

class EnhancedHostingManager:
    def __init__(self):
        self.active_processes = {}
        self.process_monitors = {}
        self.performance_monitors = {}
        self.lock = threading.Lock()
        self.system_start_time = datetime.now()
        self.user_states = {}
        self.user_manager = UserManager()
        self.file_storage = FileStorageManager()
        self.keep_running = True
        self.monitoring_interval = 10  # Increased monitoring interval
        
        # Register cleanup handlers
        atexit.register(self.cleanup_all_processes)
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.keep_running = False
        self.cleanup_all_processes()
        sys.exit(0)
    
    def cleanup_all_processes(self):
        """Cleanup all processes on exit"""
        logger.info("Cleaning up all processes...")
        with self.lock:
            process_ids = list(self.active_processes.keys())
        
        for process_id in process_ids:
            try:
                self._force_stop_process(process_id)
            except Exception as e:
                logger.error(f"Error cleaning up process {process_id}: {e}")
    
    def _force_stop_process(self, process_id):
        """Force stop a process with comprehensive cleanup"""
        with self.lock:
            process_info = self.active_processes.get(process_id)
            if not process_info:
                return
            
            process_info['stopped'] = True
            process_info['status'] = 'stopped'
        
        try:
            process = process_info['process']
            if process.poll() is None:
                # Kill entire process tree
                try:
                    parent = psutil.Process(process.pid)
                    children = parent.children(recursive=True)
                    
                    # Kill children first
                    for child in children:
                        try:
                            child.kill()
                        except:
                            pass
                    
                    # Kill parent
                    try:
                        parent.kill()
                    except:
                        pass
                except:
                    pass
                
                # Use process methods as backup
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except:
                    try:
                        process.kill()
                        process.wait(timeout=3)
                    except:
                        pass
            
            # Clean up monitoring threads
            if process_id in self.performance_monitors:
                self.performance_monitors[process_id] = None
            
            if process_id in self.process_monitors:
                self.process_monitors[process_id] = None
            
            with self.lock:
                if process_id in self.active_processes:
                    del self.active_processes[process_id]
            
            logger.info(f"Force stopped process {process_id}")
            return True
        except Exception as e:
            logger.error(f"Error force stopping process {process_id}: {e}")
            return False
    
    def set_user_state(self, user_id, state, data=None):
        """Set user state for file upload sequence"""
        self.user_states[user_id] = {
            'state': state,
            'data': data or {}
        }
    
    def get_user_state(self, user_id):
        """Get user state"""
        return self.user_states.get(user_id)
    
    def clear_user_state(self, user_id):
        """Clear user state"""
        if user_id in self.user_states:
            del self.user_states[user_id]
    
    def check_user_balance(self, user_id):
        """Check if user has enough coins"""
        return self.user_manager.get_coins(user_id) >= 1
    
    def deduct_coin(self, user_id):
        """Deduct coin for hosting"""
        self.user_manager.update_coins(user_id, -1)
    
    def install_requirements_from_file(self, requirements_path):
        """Install requirements from requirements.txt file"""
        try:
            with open(requirements_path, 'r') as f:
                requirements = f.read().splitlines()
            
            installed_packages = []
            failed_packages = []
            
            for package in requirements:
                package = package.strip()
                if package and not package.startswith('#'):  # Skip empty lines and comments
                    try:
                        logger.info(f"Installing package: {package}")
                        subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
                        installed_packages.append(package)
                        logger.info(f"Successfully installed {package}")
                    except subprocess.CalledProcessError as e:
                        logger.error(f"Failed to install {package}: {e}")
                        failed_packages.append(package)
            
            return {
                'success': True,
                'installed': installed_packages,
                'failed': failed_packages,
                'total_attempted': len(requirements),
                'total_installed': len(installed_packages),
                'total_failed': len(failed_packages)
            }
            
        except Exception as e:
            logger.error(f"Error reading requirements file: {e}")
            return {
                'success': False,
                'error': str(e),
                'installed': [],
                'failed': [],
                'total_attempted': 0,
                'total_installed': 0,
                'total_failed': 0
            }
    
    def start_hosting(self, file_path, user_id, file_name, requirements_installed=False):
        try:
            # Create a unique process ID
            process_id = f"{user_id}_{int(time.time())}"
            
            # Start the process with improved settings for 24/7 hosting
            process = subprocess.Popen(
                ['python3', '-u', file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                preexec_fn=os.setsid if os.name != 'nt' else None  # Create process group
            )
            
            # Store process info with enhanced monitoring
            with self.lock:
                self.active_processes[process_id] = {
                    'process': process,
                    'user_id': user_id,
                    'file_name': file_name,
                    'file_path': file_path,
                    'start_time': datetime.now(),
                    'last_restart': datetime.now(),
                    'status': 'running',
                    'restart_count': 0,
                    'pid': process.pid,
                    'stopped': False,
                    'last_check': time.time(),
                    'cpu_usage': 0.0,
                    'memory_usage': 0.0,
                    'data_sent': 0,
                    'data_received': 0,
                    'last_network_check': time.time(),
                    'requirements_installed': requirements_installed,
                    'health_check_count': 0,
                    'last_health_check': time.time()
                }
            
            # Start enhanced monitoring thread
            self._start_enhanced_monitoring(process_id)
            # Start performance monitoring
            self._start_performance_monitoring(process_id)
            
            logger.info(f"Started hosting process {process_id} for file {file_name} with PID {process.pid}")
            return process_id
        except Exception as e:
            logger.error(f"Error starting hosting: {e}")
            return None
    
    def _start_enhanced_monitoring(self, process_id):
        """Start enhanced monitoring thread for a process with better stability"""
        if process_id in self.process_monitors:
            return
            
        def enhanced_monitor():
            consecutive_failures = 0
            max_consecutive_failures = 3
            
            while self.keep_running:
                try:
                    with self.lock:
                        process_info = self.active_processes.get(process_id)
                        if not process_info or process_info.get('stopped'):
                            break
                    
                    process = process_info['process']
                    return_code = process.poll()
                    
                    if return_code is not None and not process_info.get('stopped'):
                        # Process stopped unexpectedly
                        consecutive_failures += 1
                        logger.warning(f"Process {process_id} stopped with return code {return_code}, restart attempt {consecutive_failures}")
                        
                        if consecutive_failures <= max_consecutive_failures:
                            time.sleep(2 ** consecutive_failures)  # Exponential backoff
                            success = self._restart_process(process_id)
                            if success:
                                consecutive_failures = 0
                                logger.info(f"Successfully restarted process {process_id}")
                            else:
                                logger.error(f"Failed to restart process {process_id}")
                        else:
                            logger.error(f"Process {process_id} failed {consecutive_failures} times, giving up")
                            with self.lock:
                                if process_id in self.active_processes:
                                    self.active_processes[process_id]['status'] = 'failed'
                            break
                    else:
                        consecutive_failures = 0  # Reset counter if process is running
                    
                    # Health check
                    current_time = time.time()
                    if current_time - process_info.get('last_health_check', 0) > 30:  # Every 30 seconds
                        with self.lock:
                            if process_id in self.active_processes:
                                self.active_processes[process_id]['health_check_count'] += 1
                                self.active_processes[process_id]['last_health_check'] = current_time
                
                except Exception as e:
                    logger.error(f"Error in enhanced monitoring for {process_id}: {e}")
                    time.sleep(5)
                
                time.sleep(self.monitoring_interval)
            
            # Clean up
            with self.lock:
                if process_id in self.process_monitors:
                    del self.process_monitors[process_id]
        
        thread = threading.Thread(target=enhanced_monitor)
        thread.daemon = True
        thread.start()
        self.process_monitors[process_id] = thread
    
    def _start_performance_monitoring(self, process_id):
        """Start performance monitoring for a process"""
        if process_id in self.performance_monitors:
            return
            
        def performance_monitor():
            while self.keep_running:
                try:
                    with self.lock:
                        process_info = self.active_processes.get(process_id)
                        if not process_info or process_info.get('stopped'):
                            break
                    
                    pid = process_info.get('pid')
                    if pid:
                        try:
                            ps_process = psutil.Process(pid)
                            cpu_percent = ps_process.cpu_percent(interval=1.0)
                            memory_info = ps_process.memory_info()
                            memory_mb = memory_info.rss / 1024 / 1024
                            
                            with self.lock:
                                if process_id in self.active_processes:
                                    self.active_processes[process_id]['cpu_usage'] = cpu_percent
                                    self.active_processes[process_id]['memory_usage'] = memory_mb
                            
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            # Process might have died, check and restart if needed
                            process = process_info['process']
                            if process.poll() is not None:
                                self._restart_process(process_id)
                    
                except Exception as e:
                    logger.error(f"Error in performance monitoring for {process_id}: {e}")
                
                time.sleep(15)  # Reduced frequency to save resources
        
        thread = threading.Thread(target=performance_monitor)
        thread.daemon = True
        thread.start()
        self.performance_monitors[process_id] = thread
    
    def _update_performance_stats(self, process_id, cpu_usage, memory_usage, data_sent, data_received):
        """Update performance stats in database"""
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE hostings SET 
            cpu_usage = ?, memory_usage = ?, data_sent = ?, data_received = ?
            WHERE process_id = ?
        ''', (cpu_usage, memory_usage, data_sent, data_received, process_id))
        conn.commit()
        conn.close()
    
    def _restart_process(self, process_id):
        """Restart a stopped process with enhanced reliability"""
        with self.lock:
            process_info = self.active_processes.get(process_id)
            if not process_info or process_info.get('stopped'):
                return False
        
        try:
            # Close old process completely with comprehensive cleanup
            old_process = process_info['process']
            if old_process.poll() is None:
                try:
                    # Kill process group
                    if os.name != 'nt':
                        os.killpg(os.getpgid(old_process.pid), signal.SIGTERM)
                    else:
                        old_process.terminate()
                    
                    old_process.wait(timeout=10)
                except:
                    try:
                        if os.name != 'nt':
                            os.killpg(os.getpgid(old_process.pid), signal.SIGKILL)
                        else:
                            old_process.kill()
                        old_process.wait(timeout=5)
                    except:
                        pass
            
            time.sleep(3)  # Increased delay for cleanup
            
            # Start new process with enhanced settings
            new_process = subprocess.Popen(
                ['python3', '-u', process_info['file_path']],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                preexec_fn=os.setsid if os.name != 'nt' else None
            )
            
            # Update process info
            with self.lock:
                if process_id in self.active_processes and not self.active_processes[process_id].get('stopped'):
                    self.active_processes[process_id]['process'] = new_process
                    self.active_processes[process_id]['pid'] = new_process.pid
                    self.active_processes[process_id]['last_restart'] = datetime.now()
                    self.active_processes[process_id]['restart_count'] = self.active_processes[process_id].get('restart_count', 0) + 1
                    self.active_processes[process_id]['status'] = 'running'
                    self.active_processes[process_id]['last_check'] = time.time()
                    self.active_processes[process_id]['cpu_usage'] = 0.0
                    self.active_processes[process_id]['memory_usage'] = 0.0
                    self.active_processes[process_id]['data_sent'] = 0
                    self.active_processes[process_id]['data_received'] = 0
                    self.active_processes[process_id]['health_check_count'] = 0
                    
                    logger.info(f"Restarted process {process_id} with new PID {new_process.pid}")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error restarting process {process_id}: {e}")
            time.sleep(5)
            # Retry once
            return self._restart_process(process_id)
    
    def stop_hosting(self, process_id):
        """Stop hosting for a process completely"""
        return self._force_stop_process(process_id)
    
    def stop_all_processes(self):
        """Stop all active processes at once"""
        with self.lock:
            process_ids = list(self.active_processes.keys())
        
        stopped_count = 0
        total_count = len(process_ids)
        
        for process_id in process_ids:
            try:
                if self.stop_hosting(process_id):
                    update_hosting_status(process_id, 'stopped')
                    delete_hosting_record(process_id)
                    stopped_count += 1
                    logger.info(f"Stopped process {process_id} as part of mass stop")
            except Exception as e:
                logger.error(f"Error stopping process {process_id} in mass stop: {e}")
        
        return stopped_count, total_count
    
    def stop_user_processes(self, user_id):
        """Stop all processes of a specific user"""
        user_processes = self.get_user_processes(user_id)
        stopped_count = 0
        total_count = len(user_processes)
        
        for process in user_processes:
            try:
                if self.stop_hosting(process['process_id']):
                    update_hosting_status(process['process_id'], 'stopped')
                    delete_hosting_record(process['process_id'])
                    stopped_count += 1
                    logger.info(f"Stopped process {process['process_id']} for user {user_id}")
            except Exception as e:
                logger.error(f"Error stopping process {process['process_id']} for user {user_id}: {e}")
        
        return stopped_count, total_count
    
    def get_hosting_stats(self, process_id):
        with self.lock:
            process_info = self.active_processes.get(process_id)
        
        if process_info:
            process = process_info['process']
            running = process.poll() is None and not process_info.get('stopped', False)
            
            uptime = (datetime.now() - process_info['start_time']).total_seconds()
            
            return {
                'running': running,
                'start_time': process_info['start_time'],
                'last_restart': process_info['last_restart'],
                'file_name': process_info['file_name'],
                'status': process_info.get('status', 'running'),
                'pid': process_info.get('pid'),
                'restart_count': process_info.get('restart_count', 0),
                'uptime': uptime,
                'process_id': process_id,
                'cpu_usage': process_info.get('cpu_usage', 0),
                'memory_usage': process_info.get('memory_usage', 0),
                'data_sent': process_info.get('data_sent', 0),
                'data_received': process_info.get('data_received', 0),
                'user_id': process_info.get('user_id'),
                'requirements_installed': process_info.get('requirements_installed', False),
                'health_check_count': process_info.get('health_check_count', 0)
            }
        return None
    
    def get_user_processes(self, user_id):
        """Get all processes for a user"""
        user_processes = []
        with self.lock:
            process_ids = list(self.active_processes.keys())
        
        for process_id in process_ids:
            process_info = self.active_processes.get(process_id)
            if process_info and process_info['user_id'] == user_id:
                stats = self.get_hosting_stats(process_id)
                if stats:
                    user_processes.append(stats)
        return user_processes
    
    def get_all_processes(self):
        """Get all active processes (for admin)"""
        all_processes = []
        with self.lock:
            process_ids = list(self.active_processes.keys())
        
        for process_id in process_ids:
            stats = self.get_hosting_stats(process_id)
            if stats:
                all_processes.append(stats)
        return all_processes
    
    def get_system_stats(self):
        """Get complete system statistics"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            
            memory = psutil.virtual_memory()
            memory_total = memory.total / (1024 ** 3)
            memory_used = memory.used / (1024 ** 3)
            memory_percent = memory.percent
            
            disk = psutil.disk_usage('/')
            disk_total = disk.total / (1024 ** 3)
            disk_used = disk.used / (1024 ** 3)
            disk_percent = disk.percent
            
            system_uptime = time.time() - psutil.boot_time()
            
            all_processes = self.get_all_processes()
            total_processes = len(all_processes)
            running_processes = len([p for p in all_processes if p['running']])
            
            total_cpu = sum(p.get('cpu_usage', 0) for p in all_processes)
            total_memory = sum(p.get('memory_usage', 0) for p in all_processes) / 1024
            
            return {
                'cpu': {
                    'percent': cpu_percent,
                    'count': cpu_count,
                    'process_usage': total_cpu
                },
                'memory': {
                    'total': memory_total,
                    'used': memory_used,
                    'percent': memory_percent,
                    'process_usage': total_memory
                },
                'disk': {
                    'total': disk_total,
                    'used': disk_used,
                    'percent': disk_percent
                },
                'system': {
                    'uptime': system_uptime,
                    'bot_uptime': (datetime.now() - self.system_start_time).total_seconds()
                },
                'processes': {
                    'total': total_processes,
                    'running': running_processes,
                    'stopped': total_processes - running_processes
                }
            }
        except Exception as e:
            logger.error(f"Error getting system stats: {e}")
            return None

# Initialize enhanced hosting manager
hosting_manager = EnhancedHostingManager()

def add_hosting_record(user_id, file_name, file_path, file_id, process_id, requirements_installed=False):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO hostings (user_id, file_name, file_path, file_id, start_time, last_restart, process_id, requirements_installed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, file_name, file_path, file_id, datetime.now().isoformat(), datetime.now().isoformat(), process_id, requirements_installed))
    except sqlite3.OperationalError as e:
        logger.warning(f"Column error, using fallback insert: {e}")
        cursor.execute('''
            INSERT INTO hostings (user_id, file_name, file_id, start_time, process_id, requirements_installed)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, file_name, file_id, datetime.now().isoformat(), process_id, requirements_installed))
    
    conn.commit()
    conn.close()

def update_hosting_status(process_id, status):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE hostings SET status = ? WHERE process_id = ?
    ''', (status, process_id))
    conn.commit()
    conn.close()

def delete_hosting_record(process_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM hostings WHERE process_id = ?', (process_id,))
    conn.commit()
    conn.close()

# Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    is_admin = user_id == ADMIN_ID
    
    # Check referral parameter first
    referred_by = None
    if context.args and len(context.args) > 0:
        try:
            referred_by = int(context.args[0])
            if referred_by == user_id:  # Prevent self-referral
                referred_by = None
        except ValueError:
            referred_by = None
    
    # Check if user exists, if not create with welcome bonus
    user_manager = hosting_manager.user_manager
    existing_user = user_manager.get_user(user_id)
    
    if not existing_user:
        success = user_manager.create_user(
            user_id=user_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            referred_by=referred_by
        )
        
        if success and referred_by:
            await update.message.reply_text(
                "🎉 Referral successful! You and your friend both received 1 coin bonus!",
                parse_mode='Markdown'
            )
    
    user_coins = user_manager.get_coins(user_id)
    
    welcome_text = f"""
🤖 Welcome to Python File Hosting Bot 🚀

💰 **Your Coins:** {user_coins} 🪙
(1 Coin = 1 Host)

Simply send me any Python (.py) file and I'll host it for you permanently!

⚠️ **IMPORTANT WARNING:**
- Do NOT upload DDoS tools, malware, or harmful scripts
- No corrupted files allowed
- All files are stored in secure channel
- Violators will be BANNED immediately by admin

Features:
✅ 24/7 Permanent Hosting with Enhanced Stability
✅ Auto-restart if stopped  
✅ Secure File Storage
✅ Coin-based System
✅ Referral Rewards

🎁 **Referral Program:** Invite friends and get 1 coin for each referral!
Your referral link: `https://t.me/{(await context.bot.get_me()).username}?start={user_id}`
    """
    
    keyboard = []
    if is_admin:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
    keyboard.extend([
        [InlineKeyboardButton("🚀 Start Hosting", callback_data="start_hosting")],
        [InlineKeyboardButton("📊 My Hostings", callback_data="my_hostings"), InlineKeyboardButton("💰 My Coins", callback_data="my_coins")],
        [InlineKeyboardButton("👥 Refer Friends", callback_data="refer_friends"), InlineKeyboardButton("🆘 Help", callback_data="help")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def mystatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mystatus command"""
    user_id = update.effective_user.id
    await show_my_hostings_message(update, context, user_id)

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban user - Admin only"""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied!")
        return
    
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    
    try:
        target_user_id = int(context.args[0])
        hosting_manager.user_manager.ban_user(target_user_id)
        
        # Stop all user processes
        stopped_count, total_count = hosting_manager.stop_user_processes(target_user_id)
        
        await update.message.reply_text(
            f"✅ User {target_user_id} has been banned!\n"
            f"Stopped {stopped_count}/{total_count} active processes."
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unban user - Admin only"""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied!")
        return
    
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    
    try:
        target_user_id = int(context.args[0])
        hosting_manager.user_manager.unban_user(target_user_id)
        await update.message.reply_text(f"✅ User {target_user_id} has been unbanned!")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast message to all users - Admin only"""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied!")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    
    message = ' '.join(context.args)
    users = hosting_manager.user_manager.get_all_users()
    
    sent_count = 0
    failed_count = 0
    
    await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
    
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user['user_id'],
                text=f"📢 **Admin Broadcast**\n\n{message}",
                parse_mode='Markdown'
            )
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user['user_id']}: {e}")
            failed_count += 1
        
        await asyncio.sleep(0.1)  # Rate limiting
    
    await update.message.reply_text(
        f"✅ Broadcast completed!\n"
        f"✅ Sent: {sent_count}\n"
        f"❌ Failed: {failed_count}"
    )

async def give_coins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Give coins to user - Admin only"""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied!")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /give <coins> <user_id>")
        return
    
    try:
        coins = int(context.args[0])
        target_user_id = int(context.args[1])
        
        hosting_manager.user_manager.update_coins(target_user_id, coins)
        
        await update.message.reply_text(
            f"✅ Added {coins} coins to user {target_user_id}\n"
            f"New balance: {hosting_manager.user_manager.get_coins(target_user_id)} coins"
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid coins or user ID!")

async def show_my_hostings_message(update, context, user_id):
    """Show user's hosting processes"""
    user_processes = hosting_manager.get_user_processes(user_id)
    
    if not user_processes:
        text = "📭 **No Active Hostings**\n\nYou don't have any running Python scripts."
        keyboard = [[InlineKeyboardButton("🚀 Start Hosting", callback_data="start_hosting")]]
        
        if hasattr(update, 'message'):
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await update.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return
    
    text = f"📊 **Your Active Hostings** ({len(user_processes)})\n\n"
    
    for i, process in enumerate(user_processes, 1):
        status_emoji = "🟢" if process['running'] else "🔴"
        uptime_str = format_uptime(process['uptime'])
        requirements_status = "✅" if process.get('requirements_installed', False) else "⏩"
        health_status = "💚" if process.get('health_check_count', 0) > 10 else "💛"
        
        text += f"{i}. **{process['file_name']}** {status_emoji} {health_status}\n"
        text += f"   ├─ 🆔 `{process['process_id']}`\n"
        text += f"   ├─ ⏰ {uptime_str}\n"
        text += f"   ├─ 🔄 {process['restart_count']} restarts\n"
        text += f"   ├─ 📦 {requirements_status} Requirements\n"
        text += f"   └─ 🖥️ CPU: {process.get('cpu_usage', 0):.1f}% | RAM: {process.get('memory_usage', 0):.1f}MB\n\n"
    
    keyboard = []
    for process in user_processes:
        keyboard.append([
            InlineKeyboardButton(f"📊 {process['file_name']}", callback_data=f"status_{process['process_id']}"),
            InlineKeyboardButton(f"🛑 Stop", callback_data=f"stop_{process['process_id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("🚀 Host More", callback_data="start_hosting")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_main")])
    
    if hasattr(update, 'message'):
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_my_hostings(query, context):
    """Show user's hosting processes in callback"""
    user_id = query.from_user.id
    
    # Check if user is banned
    if hosting_manager.user_manager.is_banned(user_id):
        await query.answer("❌ You are banned from using this bot!", show_alert=True)
        return
    
    user_processes = hosting_manager.get_user_processes(user_id)
    
    if not user_processes:
        text = "📭 **No Active Hostings**\n\nYou don't have any running Python scripts."
        keyboard = [
            [InlineKeyboardButton("🚀 Start Hosting", callback_data="start_hosting")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return
    
    text = f"📊 **Your Active Hostings** ({len(user_processes)})\n\n"
    
    for i, process in enumerate(user_processes, 1):
        status_emoji = "🟢" if process['running'] else "🔴"
        uptime_str = format_uptime(process['uptime'])
        requirements_status = "✅" if process.get('requirements_installed', False) else "⏩"
        health_status = "💚" if process.get('health_check_count', 0) > 10 else "💛"
        
        text += f"{i}. **{process['file_name']}** {status_emoji} {health_status}\n"
        text += f"   ├─ 🆔 `{process['process_id']}`\n"
        text += f"   ├─ ⏰ {uptime_str}\n"
        text += f"   ├─ 🔄 {process['restart_count']} restarts\n"
        text += f"   ├─ 📦 {requirements_status} Requirements\n"
        text += f"   └─ 🖥️ CPU: {process.get('cpu_usage', 0):.1f}% | RAM: {process.get('memory_usage', 0):.1f}MB\n\n"
    
    keyboard = []
    for process in user_processes:
        keyboard.append([
            InlineKeyboardButton(f"📊 {process['file_name']}", callback_data=f"status_{process['process_id']}"),
            InlineKeyboardButton(f"🛑 Stop", callback_data=f"stop_{process['process_id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("🚀 Host More", callback_data="start_hosting")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_main")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def format_uptime(seconds):
    """Format uptime in human readable format"""
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    
    if days > 0:
        return f"{int(days)}d {int(hours)}h {int(minutes)}m"
    elif hours > 0:
        return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
    elif minutes > 0:
        return f"{int(minutes)}m {int(seconds)}s"
    else:
        return f"{int(seconds)}s"

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_id = user.id
    is_admin = user_id == ADMIN_ID
    
    # Check if user is banned
    if hosting_manager.user_manager.is_banned(user_id):
        await query.answer("❌ You are banned from using this bot!", show_alert=True)
        return
    
    # Ensure user exists
    if not hosting_manager.user_manager.get_user(user_id):
        hosting_manager.user_manager.create_user(
            user_id=user_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
    
    if query.data == "start_hosting":
        user_coins = hosting_manager.user_manager.get_coins(user_id)
        
        if user_coins < 1:
            await query.answer("❌ You don't have enough coins! Get more coins or refer friends.", show_alert=True)
            return
        
        # Show warning message before hosting
        warning_text = """
⚠️ **SECURITY WARNING** ⚠️

Before hosting your file, please note:

🚫 **STRICTLY PROHIBITED:**
- DDoS tools & attack scripts
- Malware, viruses, or ransomware  
- Data theft programs
- System harming code
- Corrupted or harmful files

🛡️ **Violators will be BANNED immediately**

✅ **Only upload safe, legitimate Python scripts**

Do you agree to these terms?
        """
        
        keyboard = [
            [InlineKeyboardButton("✅ I Agree - Continue", callback_data="agree_terms")],
            [InlineKeyboardButton("❌ Cancel", callback_data="back_to_main")]
        ]
        
        await query.edit_message_text(
            warning_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
    elif query.data == "agree_terms":
        # Set user state to waiting for requirements choice
        hosting_manager.set_user_state(user_id, 'waiting_requirements_choice')
        
        user_coins = hosting_manager.user_manager.get_coins(user_id)
        
        keyboard = [
            [InlineKeyboardButton("📦 Upload Requirements.txt", callback_data="upload_requirements")],
            [InlineKeyboardButton("⏩ Skip Requirements", callback_data="skip_requirements")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
        ]
        
        await query.edit_message_text(
            f"📦 **Requirements Installation**\n\n"
            f"💰 **Your Coins:** {user_coins} 🪙\n"
            f"📋 **Cost:** 1 Coin per host\n\n"
            f"Do you want to install packages from requirements.txt file?\n\n"
            f"📋 **Options:**\n"
            f"• 📦 Upload Requirements.txt - Upload your requirements.txt file\n"
            f"• ⏩ Skip Requirements - Continue without requirements\n\n"
            f"💡 **Note:** If your script needs external packages, it's recommended to upload requirements.txt",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    elif query.data == "upload_requirements":
        # Set user state to waiting for requirements file
        hosting_manager.set_user_state(user_id, 'waiting_requirements_file')
        
        await query.edit_message_text(
            "📤 **Upload Requirements.txt**\n\n"
            "Please upload your `requirements.txt` file.\n\n"
            "📝 **File Format:**\n"
            "```\n"
            "package1==version\n"
            "package2>=version\n"
            "package3\n"
            "```\n\n"
            "The bot will automatically install all packages from this file.",
            parse_mode='Markdown'
        )
        
    elif query.data == "skip_requirements":
        # Set user state to waiting for Python file
        hosting_manager.set_user_state(user_id, 'waiting_python_file')
        
        await query.edit_message_text(
            "⏩ **Skipped Requirements**\n\n"
            "No requirements will be installed.\n\n"
            "📤 **Now upload your Python (.py) file**\n\n"
            "Please send your Python script file to start hosting.\n\n"
            "💾 **Note:** Your file will be securely stored in our channel.",
            parse_mode='Markdown'
        )
        
    elif query.data == "my_hostings":
        await show_my_hostings(query, context)
        
    elif query.data == "my_coins":
        await show_my_coins(query, context)
        
    elif query.data == "refer_friends":
        await show_referral_info(query, context)
        
    elif query.data == "help":
        help_text = f"""
🆘 Help Guide

How to use:
1. Click 'Start Hosting'
2. Read and accept security terms
3. Choose requirements option  
4. Upload Python file
5. File stored in secure channel
6. File hosted (1 coin deducted)

💰 **Coin System:**
- Start with 1 free coin
- 1 coin = 1 host
- Refer friends: 1 coin each
- Admin can add coins

👥 **Referral Program:**
Share your referral link:
`https://t.me/{(await context.bot.get_me()).username}?start={user_id}`

Get 1 coin for each friend who joins!

Commands:
/start - Start bot & get referral link
/mystatus - Check your hosted files
        """
        keyboard = [
            [InlineKeyboardButton("💰 My Coins", callback_data="my_coins"), InlineKeyboardButton("👥 Refer", callback_data="refer_friends")],
            [InlineKeyboardButton("🚀 Start Hosting", callback_data="start_hosting")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
        ]
        await query.edit_message_text(
            help_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    elif query.data == "back_to_main":
        hosting_manager.clear_user_state(user_id)
        await show_main_menu(query, is_admin)
    
    elif query.data == "admin_panel":
        if is_admin:
            await show_admin_panel(query, context)
        else:
            await query.answer("❌ Access denied!", show_alert=True)
    
    elif query.data == "admin_stats":
        if is_admin:
            await show_admin_stats(query, context)
        else:
            await query.answer("❌ Access denied!", show_alert=True)
    
    elif query.data == "admin_all_processes":
        if is_admin:
            await show_all_processes(query, context)
        else:
            await query.answer("❌ Access denied!", show_alert=True)
    
    elif query.data == "admin_system_stats":
        if is_admin:
            await show_system_stats(query, context)
        else:
            await query.answer("❌ Access denied!", show_alert=True)
    
    elif query.data == "admin_stop_all":
        if is_admin:
            await admin_stop_all_processes(query, context)
        else:
            await query.answer("❌ Access denied!", show_alert=True)
    
    elif query.data.startswith("admin_stop_user_"):
        if is_admin:
            user_id_param = int(query.data.replace("admin_stop_user_", ""))
            await admin_stop_user_processes(query, context, user_id_param)
        else:
            await query.answer("❌ Access denied!", show_alert=True)
    
    elif query.data.startswith("status_"):
        process_id = query.data.replace("status_", "")
        await show_process_status(query, context, process_id)
    
    elif query.data.startswith("stop_"):
        process_id = query.data.replace("stop_", "")
        await stop_process(query, context, process_id)
    
    elif query.data.startswith("admin_stop_"):
        if is_admin:
            process_id = query.data.replace("admin_stop_", "")
            await admin_stop_process(query, context, process_id)
        else:
            await query.answer("❌ Access denied!", show_alert=True)
    
    elif query.data.startswith("admin_details_"):
        if is_admin:
            process_id = query.data.replace("admin_details_", "")
            await show_admin_process_details(query, context, process_id)
        else:
            await query.answer("❌ Access denied!", show_alert=True)
    
    elif query.data == "confirm_stop_all":
        if is_admin:
            stopped_count, total_count = hosting_manager.stop_all_processes()
            
            await query.edit_message_text(
                f"✅ **All Processes Stopped Successfully!**\n\n"
                f"📊 **Results:**\n"
                f"• Total Processes: {total_count}\n"
                f"• Successfully Stopped: {stopped_count}\n"
                f"• Failed: {total_count - stopped_count}\n\n"
                f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode='Markdown'
            )
        else:
            await query.answer("❌ Access denied!", show_alert=True)

async def show_my_coins(query, context):
    """Show user's coin balance"""
    user_id = query.from_user.id
    user = hosting_manager.user_manager.get_user(user_id)
    
    if not user:
        await query.answer("❌ User not found!", show_alert=True)
        return
    
    text = f"💰 **Your Coin Balance**\n\n"
    text += f"🪙 **Coins:** {user['coins']}\n"
    text += f"👥 **Referrals:** {user['referral_count']}\n"
    text += f"📁 **Total Hosted:** {user['total_hosted']}\n"
    text += f"📅 **Member Since:** {user['join_date'][:10]}\n\n"
    
    text += f"🔗 **Your Referral Link:**\n"
    text += f"`https://t.me/{(await context.bot.get_me()).username}?start={user_id}`\n\n"
    
    text += f"💡 **Earn More Coins:**\n"
    text += f"• Refer friends: 1 coin each\n"
    text += f"• Contact admin for bonus coins\n"
    
    keyboard = [
        [InlineKeyboardButton("👥 Share Referral", callback_data="share_referral")],
        [InlineKeyboardButton("🚀 Start Hosting", callback_data="start_hosting")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
    ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_referral_info(query, context):
    """Show referral information"""
    user_id = query.from_user.id
    user = hosting_manager.user_manager.get_user(user_id)
    
    text = f"👥 **Referral Program**\n\n"
    text += f"🎉 **Earn 1 Coin for Each Friend!**\n\n"
    
    text += f"📊 **Your Stats:**\n"
    text += f"• Total Referrals: {user['referral_count']}\n"
    text += f"• Coins Earned: {user['referral_count']} 🪙\n\n"
    
    text += f"🔗 **Your Referral Link:**\n"
    text += f"`https://t.me/{(await context.bot.get_me()).username}?start={user_id}`\n\n"
    
    text += f"📣 **How to Share:**\n"
    text += f"1. Copy your link above\n"
    text += f"2. Share with friends\n"
    text += f"3. When they join, you both get 1 coin!\n\n"
    
    text += f"💡 **Tip:** Share in programming groups, with classmates, or on social media!\n"
    
    keyboard = [
        [InlineKeyboardButton("📤 Share Link", callback_data="share_referral")],
        [InlineKeyboardButton("💰 My Coins", callback_data="my_coins")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
    ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_main_menu(query, is_admin=False):
    user_id = query.from_user.id
    user_coins = hosting_manager.user_manager.get_coins(user_id)
    
    welcome_text = f"""
🤖 Welcome to Python File Hosting Bot 🚀

💰 **Your Coins:** {user_coins} 🪙
(1 Coin = 1 Host)

Simply send me any Python (.py) file and I'll host it for you permanently!
    """
    
    keyboard = []
    if is_admin:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
    keyboard.extend([
        [InlineKeyboardButton("🚀 Start Hosting", callback_data="start_hosting")],
        [InlineKeyboardButton("📊 My Hostings", callback_data="my_hostings"), InlineKeyboardButton("💰 My Coins", callback_data="my_coins")],
        [InlineKeyboardButton("👥 Refer Friends", callback_data="refer_friends"), InlineKeyboardButton("🆘 Help", callback_data="help")]
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        welcome_text,
        reply_markup=reply_markup
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    document = update.message.document
    user_state = hosting_manager.get_user_state(user.id)
    
    # Check if user is banned
    if hosting_manager.user_manager.is_banned(user.id):
        await update.message.reply_text("❌ You are banned from using this bot!")
        return
    
    # If no state, ignore the file
    if not user_state:
        await update.message.reply_text(
            "❌ Please click '🚀 Start Hosting' first to begin the hosting process.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Start Hosting", callback_data="start_hosting")]])
        )
        return
    
    state = user_state['state']
    
    if state == 'waiting_requirements_file' and document.file_name == 'requirements.txt':
        await handle_requirements_file(update, context, user, document)
    
    elif state == 'waiting_python_file' and document.file_name.endswith('.py'):
        await handle_python_file(update, context, user, document, requirements_installed=False)
    
    elif state == 'waiting_python_file_after_requirements' and document.file_name.endswith('.py'):
        await handle_python_file(update, context, user, document, requirements_installed=True)
    
    else:
        if state == 'waiting_requirements_file':
            await update.message.reply_text("❌ Please upload a valid `requirements.txt` file.")
        elif state in ['waiting_python_file', 'waiting_python_file_after_requirements']:
            await update.message.reply_text("❌ Please upload a valid Python (.py) file.")
        else:
            await update.message.reply_text("❌ Invalid file upload. Please start over.")

async def handle_requirements_file(update: Update, context: ContextTypes.DEFAULT_TYPE, user, document):
    """Handle requirements.txt file upload"""
    try:
        file = await context.bot.get_file(document.file_id)
        requirements_path = f"requirements_{user.id}_{int(time.time())}.txt"
        os.makedirs("temp_files", exist_ok=True)
        requirements_path = os.path.join("temp_files", requirements_path)
        
        await file.download_to_drive(requirements_path)
        
        installing_msg = await update.message.reply_text("📦 Installing requirements... This may take a moment.")
        
        result = hosting_manager.install_requirements_from_file(requirements_path)
        
        try:
            os.remove(requirements_path)
        except:
            pass
        
        if result['success']:
            hosting_manager.set_user_state(user.id, 'waiting_python_file_after_requirements', {
                'requirements_result': result
            })
            
            success_count = result['total_installed']
            failed_count = result['total_failed']
            
            success_text = ""
            if result['installed']:
                success_text = "✅ **Successfully Installed:**\n" + "\n".join([f"• `{pkg}`" for pkg in result['installed'][:10]])
                if len(result['installed']) > 10:
                    success_text += f"\n• ... and {len(result['installed']) - 10} more"
            
            failed_text = ""
            if result['failed']:
                failed_text = "❌ **Failed to Install:**\n" + "\n".join([f"• `{pkg}`" for pkg in result['failed'][:5]])
                if len(result['failed']) > 5:
                    failed_text += f"\n• ... and {len(result['failed']) - 5} more"
            
            await installing_msg.edit_text(
                f"✅ **Requirements Installation Complete!**\n\n"
                f"📊 **Summary:**\n"
                f"• 📦 Attempted: {result['total_attempted']} packages\n"
                f"• ✅ Installed: {success_count} packages\n"
                f"• ❌ Failed: {failed_count} packages\n\n"
                f"{success_text}\n\n"
                f"{failed_text}\n\n"
                f"📤 **Now upload your Python (.py) file**",
                parse_mode='Markdown'
            )
        else:
            await installing_msg.edit_text(
                f"❌ **Failed to install requirements**\n\n"
                f"Error: {result['error']}\n\n"
                "You can still upload your Python file, but it might not work without the required packages.",
                parse_mode='Markdown'
            )
            hosting_manager.set_user_state(user.id, 'waiting_python_file')
            
    except Exception as e:
        logger.error(f"Error handling requirements file: {e}")
        await update.message.reply_text(f"❌ Error processing requirements file: {e}")
        hosting_manager.set_user_state(user.id, 'waiting_python_file')

async def handle_python_file(update: Update, context: ContextTypes.DEFAULT_TYPE, user, document, requirements_installed=False):
    """Handle Python file upload with secure storage"""
    if not document.file_name.endswith('.py'):
        await update.message.reply_text("❌ Please send only Python (.py) files.")
        return
    
    user_id = user.id
    
    # Check coin balance
    if not hosting_manager.check_user_balance(user_id):
        await update.message.reply_text(
            "❌ You don't have enough coins! You need 1 coin to host a file.\n\n"
            "💡 Get more coins by referring friends or contact admin.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 My Coins", callback_data="my_coins")],
                [InlineKeyboardButton("👥 Refer Friends", callback_data="refer_friends")]
            ])
        )
        hosting_manager.clear_user_state(user_id)
        return
    
    # Download file
    file = await context.bot.get_file(document.file_id)
    file_path = f"hosted_files/{user.id}_{int(time.time())}_{document.file_name}"
    os.makedirs("hosted_files", exist_ok=True)
    
    await file.download_to_drive(file_path)
    os.chmod(file_path, 0o755)
    
    # Read file content for basic validation
    try:
        with open(file_path, 'r') as f:
            file_content = f.read()
        
        # Basic Python syntax check
        compile(file_content, document.file_name, 'exec')
            
    except Exception as e:
        await update.message.reply_text(f"❌ Invalid Python file: {e}")
        try:
            os.remove(file_path)
        except:
            pass
        hosting_manager.clear_user_state(user_id)
        return
    
    # Store file in channel
    storing_msg = await update.message.reply_text("💾 **Storing file in secure channel...**")
    
    try:
        file_size = os.path.getsize(file_path)
        channel_message_id = await hosting_manager.file_storage.store_file_in_channel(
            context, user_id, document.file_name, file_path, file_size
        )
        
        if channel_message_id:
            await storing_msg.edit_text("✅ **File securely stored in channel!**")
        else:
            await storing_msg.edit_text("⚠️ **File storage failed, but hosting will continue.**")
            
    except Exception as e:
        logger.error(f"Error storing file in channel: {e}")
        await storing_msg.edit_text("⚠️ **File storage failed, but hosting will continue.**")
    
    # Deduct coin and start hosting
    hosting_manager.deduct_coin(user_id)
    hosting_manager.user_manager.increment_hosted_count(user_id)
    
    process_id = hosting_manager.start_hosting(file_path, user.id, document.file_name, requirements_installed)
    
    if process_id:
        add_hosting_record(user.id, document.file_name, file_path, document.file_id, process_id, requirements_installed)
        
        hosting_manager.clear_user_state(user_id)
        
        await asyncio.sleep(2)
        
        stats = hosting_manager.get_hosting_stats(process_id)
        
        if stats and stats['running']:
            requirements_status = "✅ With Requirements" if requirements_installed else "⏩ Without Requirements"
            user_coins = hosting_manager.user_manager.get_coins(user_id)
            
            keyboard = [
                [InlineKeyboardButton("📊 View Status", callback_data=f"status_{process_id}")],
                [InlineKeyboardButton("📋 My Hostings", callback_data="my_hostings"), InlineKeyboardButton("💰 My Coins", callback_data="my_coins")]
            ]
            
            await update.message.reply_text(
                f"✅ **Hosting Started Successfully!** 🎉\n\n"
                f"📁 **File:** {document.file_name}\n"
                f"📦 **Mode:** {requirements_status}\n"
                f"💾 **Storage:** ✅ Channel Stored\n"
                f"💰 **Cost:** 1 Coin (Remaining: {user_coins} 🪙)\n"
                f"🚀 **Status:** 🟢 Running\n"
                f"⏰ **Started:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"🆔 **Process ID:** `{process_id}`\n\n"
                f"Your script is now running permanently with enhanced 24/7 stability!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"⚠️ **Hosting Started with Issues**\n\n"
                f"📁 File: {document.file_name}\n"
                f"🔴 Status: Needs restart\n\n"
                f"The system will automatically restart your script."
            )
        
    else:
        await update.message.reply_text("❌ Failed to start hosting. Please try again with a different file.")
        # Refund coin if hosting failed
        hosting_manager.user_manager.update_coins(user_id, 1)
        try:
            os.remove(file_path)
        except:
            pass
        hosting_manager.clear_user_state(user_id)

async def show_process_status(query, context, process_id):
    """Show detailed status of a process"""
    stats = hosting_manager.get_hosting_stats(process_id)
    
    if not stats:
        await query.answer("❌ Process not found!", show_alert=True)
        return
    
    status_emoji = "🟢" if stats['running'] else "🔴"
    status_text = "Running" if stats['running'] else "Stopped"
    uptime_str = format_uptime(stats['uptime'])
    requirements_status = "✅ Installed" if stats.get('requirements_installed', False) else "⏩ Skipped"
    health_status = "💚 Stable" if stats.get('health_check_count', 0) > 10 else "💛 Initializing"
    
    text = f"📊 **Process Status**\n\n"
    text += f"📁 **File:** {stats['file_name']}\n"
    text += f"🚀 **Status:** {status_emoji} {status_text}\n"
    text += f"💚 **Health:** {health_status}\n"
    text += f"🆔 **Process ID:** `{process_id}`\n"
    text += f"📛 **PID:** {stats.get('pid', 'N/A')}\n"
    text += f"⏰ **Uptime:** {uptime_str}\n"
    text += f"🕒 **Started:** {stats['start_time'].strftime('%Y-%m-%d %H:%M:%S')}\n"
    text += f"🔁 **Restarts:** {stats['restart_count']}\n"
    text += f"📦 **Requirements:** {requirements_status}\n\n"
    
    text += f"🖥️ **Performance:**\n"
    text += f"• CPU Usage: {stats.get('cpu_usage', 0):.1f}%\n"
    text += f"• Memory Usage: {stats.get('memory_usage', 0):.1f} MB\n"
    text += f"• Data Sent: {stats.get('data_sent', 0):.1f} B/s\n"
    text += f"• Data Received: {stats.get('data_received', 0):.1f} B/s\n"
    text += f"• Health Checks: {stats.get('health_check_count', 0)}\n"
    
    keyboard = [
        [InlineKeyboardButton("🛑 Stop Process", callback_data=f"stop_{process_id}")],
        [InlineKeyboardButton("📋 My Hostings", callback_data="my_hostings"), InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
    ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def stop_process(query, context, process_id):
    """Stop a specific process"""
    user_id = query.from_user.id
    stats = hosting_manager.get_hosting_stats(process_id)
    
    if not stats:
        await query.answer("❌ Process not found!", show_alert=True)
        return
    
    if stats['user_id'] != user_id and user_id != ADMIN_ID:
        await query.answer("❌ You can only stop your own processes!", show_alert=True)
        return
    
    if hosting_manager.stop_hosting(process_id):
        update_hosting_status(process_id, 'stopped')
        delete_hosting_record(process_id)
        
        await query.answer("✅ Process stopped successfully!", show_alert=True)
        await show_my_hostings(query, context)
    else:
        await query.answer("❌ Failed to stop process!", show_alert=True)

async def show_admin_panel(query, context):
    """Show admin panel"""
    text = "👑 **Admin Panel**\n\n"
    text += "Welcome to the admin control panel!\n\n"
    
    system_stats = hosting_manager.get_system_stats()
    if system_stats:
        text += "📊 **Current System Overview:**\n"
        text += f"• CPU Usage: {system_stats['cpu']['percent']}%\n"
        text += f"• Memory Usage: {system_stats['memory']['percent']}%\n"
        text += f"• Total Processes: {system_stats['processes']['total']}\n"
        text += f"• Running Processes: {system_stats['processes']['running']}\n"
    
    keyboard = [
        [InlineKeyboardButton("📈 System Stats", callback_data="admin_system_stats"), InlineKeyboardButton("👁️ All Processes", callback_data="admin_all_processes")],
        [InlineKeyboardButton("🖥️ Live Monitor", callback_data="admin_stats")],
        [InlineKeyboardButton("🛑 Stop All Processes", callback_data="admin_stop_all")],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_stop_all_processes(query, context):
    """Stop all processes at once"""
    try:
        keyboard = [
            [InlineKeyboardButton("✅ Yes, Stop All", callback_data="confirm_stop_all")],
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")]
        ]
        
        all_processes = hosting_manager.get_all_processes()
        await query.edit_message_text(
            "⚠️ **Stop All Processes** ⚠️\n\n"
            "Are you sure you want to stop **ALL** running processes?\n\n"
            "This action will:\n"
            "• Stop every Python script\n"
            "• Affect all users\n"
            "• Cannot be undone\n\n"
            f"**Total processes running:** {len(all_processes)}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in admin_stop_all_processes: {e}")
        await query.answer("❌ Error preparing stop all", show_alert=True)

async def show_admin_stats(query, context):
    """Show admin statistics"""
    system_stats = hosting_manager.get_system_stats()
    
    if not system_stats:
        await query.answer("❌ Error getting system stats", show_alert=True)
        return
    
    text = "📊 **System Statistics**\n\n"
    
    text += "🖥️ **CPU Usage:**\n"
    text += f"• System: {system_stats['cpu']['percent']}%\n"
    text += f"• Processes: {system_stats['cpu']['process_usage']:.1f}%\n"
    text += f"• Cores: {system_stats['cpu']['count']}\n\n"
    
    text += "💾 **Memory Usage:**\n"
    text += f"• System: {system_stats['memory']['percent']}%\n"
    text += f"• Used: {system_stats['memory']['used']:.1f}GB / {system_stats['memory']['total']:.1f}GB\n"
    text += f"• Processes: {system_stats['memory']['process_usage']:.1f}GB\n\n"
    
    text += "💽 **Disk Usage:**\n"
    text += f"• Used: {system_stats['disk']['used']:.1f}GB / {system_stats['disk']['total']:.1f}GB\n"
    text += f"• Usage: {system_stats['disk']['percent']}%\n\n"
    
    text += "⏰ **Uptime:**\n"
    text += f"• System: {format_uptime(system_stats['system']['uptime'])}\n"
    text += f"• Bot: {format_uptime(system_stats['system']['bot_uptime'])}\n\n"
    
    text += "🔧 **Processes:**\n"
    text += f"• Total: {system_stats['processes']['total']}\n"
    text += f"• Running: {system_stats['processes']['running']}\n"
    text += f"• Stopped: {system_stats['processes']['stopped']}\n"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]
    ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_all_processes(query, context):
    """Show all processes for admin"""
    all_processes = hosting_manager.get_all_processes()
    
    if not all_processes:
        text = "📭 **No Active Processes**\n\nNo processes are currently running."
        keyboard = [[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return
    
    text = f"👁️ **All Active Processes** ({len(all_processes)})\n\n"
    
    for i, process in enumerate(all_processes, 1):
        status_emoji = "🟢" if process['running'] else "🔴"
        uptime_str = format_uptime(process['uptime'])
        health_status = "💚" if process.get('health_check_count', 0) > 10 else "💛"
        
        text += f"{i}. **{process['file_name']}** {status_emoji} {health_status}\n"
        text += f"   ├─ 👤 User: {process['user_id']}\n"
        text += f"   ├─ 🆔 `{process['process_id']}`\n"
        text += f"   ├─ ⏰ {uptime_str}\n"
        text += f"   ├─ 🔄 {process['restart_count']} restarts\n"
        text += f"   └─ 🖥️ CPU: {process.get('cpu_usage', 0):.1f}% | RAM: {process.get('memory_usage', 0):.1f}MB\n\n"
    
    keyboard = []
    for process in all_processes:
        keyboard.append([
            InlineKeyboardButton(f"📊 {process['file_name'][:10]}", callback_data=f"admin_details_{process['process_id']}"),
            InlineKeyboardButton(f"🛑 Stop", callback_data=f"admin_stop_{process['process_id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("🛑 Stop All", callback_data="admin_stop_all")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_system_stats(query, context):
    """Show detailed system statistics"""
    system_stats = hosting_manager.get_system_stats()
    
    if not system_stats:
        await query.answer("❌ Error getting system stats", show_alert=True)
        return
    
    text = "📈 **Detailed System Statistics**\n\n"
    
    # CPU Information
    text += "🖥️ **CPU Information:**\n"
    text += f"• Usage: {system_stats['cpu']['percent']}%\n"
    text += f"• Process Usage: {system_stats['cpu']['process_usage']:.1f}%\n"
    text += f"• Cores: {system_stats['cpu']['count']}\n\n"
    
    # Memory Information
    memory_percent = system_stats['memory']['percent']
    memory_used = system_stats['memory']['used']
    memory_total = system_stats['memory']['total']
    
    text += "💾 **Memory Information:**\n"
    text += f"• Usage: {memory_percent}%\n"
    text += f"• Used: {memory_used:.2f} GB\n"
    text += f"• Total: {memory_total:.2f} GB\n"
    text += f"• Available: {memory_total - memory_used:.2f} GB\n"
    text += f"• Process Usage: {system_stats['memory']['process_usage']:.2f} GB\n\n"
    
    # Disk Information
    disk_percent = system_stats['disk']['percent']
    disk_used = system_stats['disk']['used']
    disk_total = system_stats['disk']['total']
    
    text += "💽 **Disk Information:**\n"
    text += f"• Usage: {disk_percent}%\n"
    text += f"• Used: {disk_used:.2f} GB\n"
    text += f"• Total: {disk_total:.2f} GB\n"
    text += f"• Free: {disk_total - disk_used:.2f} GB\n\n"
    
    # Uptime Information
    system_uptime = system_stats['system']['uptime']
    bot_uptime = system_stats['system']['bot_uptime']
    
    text += "⏰ **Uptime Information:**\n"
    text += f"• System: {format_uptime(system_uptime)}\n"
    text += f"• Bot: {format_uptime(bot_uptime)}\n\n"
    
    # Process Information
    text += "🔧 **Process Information:**\n"
    text += f"• Total: {system_stats['processes']['total']}\n"
    text += f"• Running: {system_stats['processes']['running']}\n"
    text += f"• Stopped: {system_stats['processes']['stopped']}\n"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_system_stats")],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]
    ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_admin_process_details(query, context, process_id):
    """Show detailed admin view of a process"""
    stats = hosting_manager.get_hosting_stats(process_id)
    
    if not stats:
        await query.answer("❌ Process not found!", show_alert=True)
        return
    
    status_emoji = "🟢" if stats['running'] else "🔴"
    status_text = "Running" if stats['running'] else "Stopped"
    uptime_str = format_uptime(stats['uptime'])
    health_status = "💚 Stable" if stats.get('health_check_count', 0) > 10 else "💛 Initializing"
    
    text = f"👑 **Admin Process Details**\n\n"
    text += f"📁 **File:** {stats['file_name']}\n"
    text += f"👤 **User ID:** {stats['user_id']}\n"
    text += f"🚀 **Status:** {status_emoji} {status_text}\n"
    text += f"💚 **Health:** {health_status}\n"
    text += f"🆔 **Process ID:** `{process_id}`\n"
    text += f"📛 **PID:** {stats.get('pid', 'N/A')}\n"
    text += f"⏰ **Uptime:** {uptime_str}\n"
    text += f"🕒 **Started:** {stats['start_time'].strftime('%Y-%m-%d %H:%M:%S')}\n"
    text += f"🔄 **Last Restart:** {stats['last_restart'].strftime('%Y-%m-%d %H:%M:%S')}\n"
    text += f"🔁 **Restart Count:** {stats['restart_count']}\n"
    text += f"📦 **Requirements:** {'✅ Installed' if stats.get('requirements_installed', False) else '⏩ Skipped'}\n"
    text += f"💚 **Health Checks:** {stats.get('health_check_count', 0)}\n\n"
    
    text += f"🖥️ **Performance Metrics:**\n"
    text += f"• CPU Usage: {stats.get('cpu_usage', 0):.1f}%\n"
    text += f"• Memory Usage: {stats.get('memory_usage', 0):.1f} MB\n"
    text += f"• Data Sent Rate: {stats.get('data_sent', 0):.1f} B/s\n"
    text += f"• Data Received Rate: {stats.get('data_received', 0):.1f} B/s\n"
    
    keyboard = [
        [InlineKeyboardButton("🛑 Stop Process", callback_data=f"admin_stop_{process_id}")],
        [InlineKeyboardButton("📋 All Processes", callback_data="admin_all_processes"), InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]
    ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_stop_process(query, context, process_id):
    """Admin stop a specific process"""
    if hosting_manager.stop_hosting(process_id):
        update_hosting_status(process_id, 'stopped')
        delete_hosting_record(process_id)
        
        await query.answer("✅ Process stopped successfully!", show_alert=True)
        await show_all_processes(query, context)
    else:
        await query.answer("❌ Failed to stop process!", show_alert=True)

async def admin_stop_user_processes(query, context, user_id):
    """Admin stop all processes of a user"""
    stopped_count, total_count = hosting_manager.stop_user_processes(user_id)
    
    await query.answer(f"✅ Stopped {stopped_count}/{total_count} processes for user {user_id}!", show_alert=True)
    await show_all_processes(query, context)

def main():
    # Create necessary directories
    os.makedirs("hosted_files", exist_ok=True)
    os.makedirs("temp_files", exist_ok=True)
    
    try:
        # Initialize bot
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("mystatus", mystatus_command))
        application.add_handler(CommandHandler("ban", ban_command))
        application.add_handler(CommandHandler("unban", unban_command))
        application.add_handler(CommandHandler("broadcast", broadcast_command))
        application.add_handler(CommandHandler("give", give_coins_command))
        application.add_handler(CallbackQueryHandler(handle_callback))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        
        # Start bot
        print("🤖 Bot is running...")
        print("📊 Enhanced Hosting Manager initialized")
        print("💾 Database ready")
        print("🔄 Enhanced Auto-restart system active")
        print("💚 24/7 Stability improvements applied")
        print(f"🐍 Using Python 3 for hosting")
        print(f"👑 Admin ID: {ADMIN_ID}")
        print(f"💾 File Storage Channel: {CHANNEL_ID}")
        print("💰 Coin System activated")
        print("👥 Referral Program ready")
        print("✅ File Channel Storage Fixed")
        print("✅ Referral System Fixed")
        print("✅ All Functions Defined")
        print("✅ Enhanced 24/7 Hosting Stability Applied")
        application.run_polling()
        
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        logger.error(f"Failed to start bot: {e}")

if __name__ == '__main__':
    main()
