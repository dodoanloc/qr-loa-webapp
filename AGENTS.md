# QR Tài khoản Loa Thần Tài — Agent Context

- Slug: `qr-loa`
- Source: `/home/locdodoan/webapps/projects/qr-loa-webapp`
- Service: `qr-loa-webapp.service`
- Port: `8895`
- Runtime: Python
- Data class: internal

## Rules

- Never commit `.env`, generated QR data containing customer identifiers, DB dumps, uploads, or backups.
- Production checkout is deploy-only; use worktrees for feature/fix/review work.
- Verify exact service and served UI/API after approved deploy.

Registry: `/home/locdodoan/webapps/registry/projects.yaml`
