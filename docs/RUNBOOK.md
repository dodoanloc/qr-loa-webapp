# Runbook — QR LOA

## Đường dẫn
```bash
cd /home/locdodoan/.openclaw/workspace/qr-loa-webapp
```

## Kiểm tra nhanh
```bash
git status
python3 --version
```

## Chạy thủ công
```bash
python3 server.py
```

## Service
```bash
systemctl --user status qr-loa-webapp --no-pager
systemctl --user restart qr-loa-webapp
journalctl --user -u qr-loa-webapp -n 100 --no-pager
```

## Health check
```bash
curl -I http://127.0.0.1:CHUA_DANG_KY || true
```

## Backup nhanh
```bash
/home/locdodoan/webapps/scripts/backup-webapps.sh qr-loa-webapp
```
