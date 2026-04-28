// Update balance display
function updateBalance(balance) {
    document.getElementById('balance').textContent = `$${parseFloat(balance).toFixed(2)}`;
}

// Show modal
function showModal(type) {
    document.getElementById(`${type}Modal`).style.display = 'block';
    document.body.style.overflow = 'hidden';
}

// Close modal
function closeModal(type) {
    document.getElementById(`${type}Modal`).style.display = 'none';
    document.body.style.overflow = 'auto';
}

// Perform deposit
async function performDeposit() {
    const amount = parseFloat(document.getElementById('depositAmount').value);
    
    if (!amount || amount <= 0) {
        alert('Please enter a valid amount');
        return;
    }
    
    try {
        const response = await fetch('/api/deposit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount: amount })
        });
        
        const data = await response.json();
        
        if (data.success) {
            updateBalance(data.balance);
            closeModal('deposit');
            document.getElementById('depositAmount').value = '';
            location.reload(); // Refresh to update transactions
        } else {
            alert(data.message);
        }
    } catch (error) {
        alert('Error processing deposit');
    }
}

// Perform withdrawal
async function performWithdraw() {
    const amount = parseFloat(document.getElementById('withdrawAmount').value);
    
    if (!amount || amount <= 0) {
        alert('Please enter a valid amount');
        return;
    }
    
    try {
        const response = await fetch('/api/withdraw', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount: amount })
        });
        
        const data = await response.json();
        
        if (data.success) {
            updateBalance(data.balance);
            closeModal('withdraw');
            document.getElementById('withdrawAmount').value = '';
            location.reload();
        } else {
            alert(data.message);
        }
    } catch (error) {
        alert('Error processing withdrawal');
    }
}

// Perform send money
async function performSend() {
    const amount = parseFloat(document.getElementById('sendAmount').value);
    const recipient = document.getElementById('recipient').value;
    
    if (!amount || amount <= 0) {
        alert('Please enter a valid amount');
        return;
    }
    
    if (!recipient) {
        alert('Please enter recipient username');
        return;
    }
    
    try {
        const response = await fetch('/api/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount: amount, recipient: recipient })
        });
        
        const data = await response.json();
        
        if (data.success) {
            updateBalance(data.balance);
            closeModal('send');
            document.getElementById('sendAmount').value = '';
            document.getElementById('recipient').value = '';
            location.reload();
        } else {
            alert(data.message);
        }
    } catch (error) {
        alert('Error processing transfer');
    }
}

// Close modals on outside click
window.onclick = function(event) {
    const modals = document.querySelectorAll('.modal');
    modals.forEach(modal => {
        if (event.target === modal) {
            modal.style.display = 'none';
            document.body.style.overflow = 'auto';
        }
    });
}

// Input formatting
document.querySelectorAll('input[type="number"]').forEach(input => {
    input.addEventListener('input', function() {
        if (this.value < 0) this.value = 0;
    });
});

function initGlobalUI() {
    document.querySelectorAll('.password-toggle').forEach(button => {
        button.addEventListener('click', () => {
            const input = button.closest('.input-group').querySelector('input');
            if (!input) return;
            const isPassword = input.type === 'password';
            input.type = isPassword ? 'text' : 'password';
            button.innerHTML = isPassword ? '<i class="fas fa-eye-slash"></i>' : '<i class="fas fa-eye"></i>';
        });
    });

    const alerts = document.querySelectorAll('.alert');
    if (alerts.length) {
        setTimeout(() => {
            alerts.forEach(alert => alert.style.display = 'none');
        }, 3000);
    }
}

document.addEventListener('DOMContentLoaded', initGlobalUI);