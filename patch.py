import os

file_path = os.path.join(os.path.dirname(__file__), 'static', 'app.js')

with open(file_path, 'r') as f:
    content = f.read()

# Replace all alerts with showToast, defaulting to error since most alerts are errors
content = content.replace("alert(", "showToast(")

# Add the toast implementation
toast_code = """
// ================= TOAST NOTIFICATIONS =================
function showToast(message, type = 'error') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  
  if (message.includes('success')) {
      type = 'success';
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  
  let iconName = 'info';
  if (type === 'error') iconName = 'alert-circle';
  if (type === 'success') iconName = 'check-circle';

  toast.innerHTML = `
    <i data-lucide="${iconName}" class="toast-icon"></i>
    <div class="toast-message">${message}</div>
    <button class="toast-close"><i data-lucide="x" style="width:16px;height:16px;"></i></button>
  `;

  container.appendChild(toast);
  lucide.createIcons({ root: toast });

  const closeBtn = toast.querySelector('.toast-close');
  
  const hideToast = () => {
    toast.classList.add('toast-hiding');
    toast.addEventListener('animationend', () => {
      if (toast.parentElement) {
        toast.remove();
      }
    });
  };

  closeBtn.addEventListener('click', hideToast);
  setTimeout(hideToast, 5000); // Auto hide after 5 seconds
}
"""

with open(file_path, 'w') as f:
    f.write(content + "\n" + toast_code)
