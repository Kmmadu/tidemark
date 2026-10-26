// AutoConfigBackup - Main JavaScript
// Handles dynamic updates, API calls, and UI interactions

'use strict';

// Utility functions
const API = {
    async triggerBackup(deviceName = null) {
        const url = deviceName 
            ? `/api/backup/trigger/${deviceName}`
            : '/api/backup/trigger';
        
        try {
            const response = await fetch(url, { method: 'POST' });
            const data = await response.json();
            
            if (response.ok) {
                this.showMessage('success', data.message || 'Backup triggered successfully');
                return true;
            } else {
                this.showMessage('danger', data.message || 'Backup failed');
                return false;
            }
        } catch (error) {
            this.showMessage('danger', 'Network error: ' + error.message);
            return false;
        }
    },
    
    async loadBackupHistory() {
        try {
            const response = await fetch('/api/backups');
            if (response.ok) {
                const backups = await response.json();
                return backups;
            }
        } catch (error) {
            console.error('Failed to load history:', error);
        }
        return [];
    },
    
    showMessage(category, message) {
        // Remove existing flashes
        const flashContainer = document.querySelector('.flashes');
        if (flashContainer) {
            const div = document.createElement('div');
            div.className = `flash flash-${category}`;
            div.textContent = message;
            flashContainer.appendChild(div);
            
            // Auto-remove after 5 seconds
            setTimeout(() => div.remove(), 5000);
        } else {
            alert(message); // Fallback
        }
    }
};

// Real-time clock update
function updateClock() {
    const clockEl = document.getElementById('clock');
    if (clockEl) {
        const now = new Date();
        clockEl.textContent = now.toLocaleString('en-GB', { 
            hour12: false,
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }
}

// Auto-refresh dashboard
let autoRefreshInterval = null;

function startAutoRefresh(seconds = 30) {
    if (autoRefreshInterval) clearInterval(autoRefreshInterval);
    autoRefreshInterval = setInterval(() => {
        if (window.location.pathname === '/' || window.location.pathname === '/dashboard') {
            fetch('/api/backups/stats')
                .then(res => res.json())
                .then(data => {
                    updateStats(data);
                })
                .catch(err => console.debug('Auto-refresh skipped:', err));
        }
    }, seconds * 1000);
}

function updateStats(stats) {
    // Update stats if elements exist
    const deviceCount = document.getElementById('stat-devices');
    const backupCount = document.getElementById('stat-backups');
    const lastBackup = document.getElementById('stat-last');
    
    if (deviceCount) deviceCount.textContent = stats.devices || '0';
    if (backupCount) backupCount.textContent = stats.backups || '0';
    if (lastBackup && stats.last_backup) lastBackup.textContent = stats.last_backup;
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    updateClock();
    setInterval(updateClock, 1000);
    // Backup buttons use inline onclick handlers in templates
    startAutoRefresh(30);
});

// Export for use in console debugging
window.AutoConfigBackup = { API };