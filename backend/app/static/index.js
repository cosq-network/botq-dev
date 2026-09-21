fetch('/health/ready').then(r => r.json()).then(d => {
  document.getElementById('status').textContent = d.data.status + ' (db ' + d.data.database + ')';
}).catch(() => {
  document.getElementById('status').textContent = 'unreachable';
});
