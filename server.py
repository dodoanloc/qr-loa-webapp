#!/usr/bin/env python3
"""
QR Tài khoản / Loa Thần Tài Registration Server
Port: 8895
"""

import os
import json
import logging
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from urllib.request import urlopen, Request
import psycopg2
from psycopg2.extras import RealDictCursor, Json

PORT = 8895
HOST = '0.0.0.0'
PUBLIC_DIR = Path(__file__).parent / 'public'

DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', '5432')),
    'database': os.getenv('DB_NAME', 'cccd_records'),
    'user': os.getenv('DB_USER', 'cccd_app'),
    'password': os.getenv('DB_PASSWORD', '')
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def get_db_connection():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)
    return psycopg2.connect(**DB_CONFIG)


def row_to_airtable_shape(row):
    created = row.get('airtable_created_time') or row.get('imported_at')
    fields = row.get('raw_fields') or {}
    normalized = {
        'Loại đăng ký': row.get('loai_dang_ky'),
        'Số tài khoản': row.get('so_tai_khoan'),
        'Số điện thoại': row.get('so_dien_thoai'),
        'Tên khách hàng': row.get('ten_khach_hang'),
        'Cán bộ quản lý': row.get('can_bo_quan_ly'),
        'Ghi chú': row.get('ghi_chu'),
        'Tên chủ hộ': row.get('ten_chu_ho'),
        'Số CCCD': row.get('so_cccd'),
        'Ngày cấp': row.get('ngay_cap').isoformat() if row.get('ngay_cap') else None,
        'Nơi cấp': row.get('noi_cap'),
        'Địa chỉ': row.get('dia_chi'),
        'Yêu cầu in mẫu biểu': row.get('yeu_cau_in_mau_bieu') or 'Không',
    }
    for key, value in normalized.items():
        if value is not None:
            fields[key] = value
    return {
        'id': row.get('airtable_id') or f"pg_{row.get('id')}",
        'createdTime': created.isoformat() if created else None,
        'fields': fields,
    }


def init_database():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS regis_customer_records (
                id BIGSERIAL,
                airtable_id TEXT PRIMARY KEY,
                airtable_created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                loai_dang_ky TEXT,
                so_tai_khoan TEXT,
                so_dien_thoai TEXT,
                ten_khach_hang TEXT,
                can_bo_quan_ly TEXT,
                ghi_chu TEXT,
                ten_chu_ho TEXT,
                so_cccd TEXT,
                ngay_cap DATE,
                noi_cap TEXT,
                dia_chi TEXT,
                yeu_cau_in_mau_bieu TEXT DEFAULT 'Không',
                raw_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
                imported_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_regis_customer_records_created ON regis_customer_records(airtable_created_time DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_regis_customer_records_account ON regis_customer_records(so_tai_khoan);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_regis_customer_records_staff ON regis_customer_records(can_bo_quan_ly);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_regis_customer_records_type ON regis_customer_records(loai_dang_ky);")
        conn.commit()
        cursor.close(); conn.close()
        logger.info("Database initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False


class RequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/regis-records':
            self.handle_get_regis_records(parsed)
        elif parsed.path == '/api/regis-records/check':
            self.handle_check_duplicate(parsed)
        elif parsed.path == '/api/vietqr-image':
            self.handle_vietqr_image(parsed)
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/regis-records':
            self.handle_create_regis_record()
        else:
            self.send_error(404, "Not Found")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/regis-records/'):
            record_id = parsed.path.rsplit('/', 1)[-1]
            self.handle_delete_regis_record(record_id)
        else:
            self.send_error(404, "Not Found")

    def handle_get_regis_records(self, parsed):
        try:
            qs = parse_qs(parsed.query)
            limit = min(int(qs.get('limit', ['10000'])[0]), 10000)
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT * FROM regis_customer_records
                ORDER BY airtable_created_time DESC NULLS LAST, imported_at DESC
                LIMIT %s
            """, (limit,))
            records = [row_to_airtable_shape(dict(row)) for row in cursor.fetchall()]
            cursor.close(); conn.close()
            self.send_json_response({'records': records})
        except Exception as e:
            logger.error(f"Error fetching regis records: {e}")
            self.send_error_response(500, str(e))

    def handle_check_duplicate(self, parsed):
        try:
            qs = parse_qs(parsed.query)
            account = (qs.get('account_number', [''])[0] or '').strip()
            reg_type = (qs.get('loai_dang_ky', [''])[0] or '').strip()
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT * FROM regis_customer_records
                WHERE so_tai_khoan = %s AND loai_dang_ky = %s
                ORDER BY airtable_created_time DESC NULLS LAST
                LIMIT 1
            """, (account, reg_type))
            row = cursor.fetchone()
            cursor.close(); conn.close()
            self.send_json_response({'records': [row_to_airtable_shape(dict(row))] if row else []})
        except Exception as e:
            logger.error(f"Error checking duplicate: {e}")
            self.send_error_response(500, str(e))

    def handle_vietqr_image(self, parsed):
        try:
            qs = parse_qs(parsed.query)
            acc = (qs.get('acc', [''])[0] or '').strip()
            name = (qs.get('name', [''])[0] or '').strip()
            if not acc:
                self.send_error_response(400, 'Missing account number')
                return
            
            name_param = quote(name) if name else ''
            acc_param = quote(acc, safe='')
            vietqr_url = f'https://img.vietqr.io/image/970405-{acc_param}-qr_only.png?amount=0&accountName={name_param}'
            
            req = Request(vietqr_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urlopen(req, timeout=10) as resp:
                content = resp.read()
                content_type = resp.headers.get('Content-Type', 'image/png')
            
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'public, max-age=3600')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            logger.error(f"Error proxying VietQR: {e}")
            self.send_error_response(500, str(e))

    def handle_delete_regis_record(self, record_id):
        try:
            record_id = self.clean(record_id)
            if not record_id:
                self.send_error_response(400, 'Thiếu ID bản ghi')
                return
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM regis_customer_records WHERE airtable_id = %s RETURNING airtable_id", (record_id,))
            deleted = cursor.fetchone()
            conn.commit(); cursor.close(); conn.close()
            if not deleted:
                self.send_error_response(404, 'Không tìm thấy bản ghi')
                return
            logger.info(f"Deleted regis record {record_id}")
            self.send_json_response({'success': True, 'deleted_id': record_id})
        except Exception as e:
            logger.error(f"Error deleting regis record: {e}")
            self.send_error_response(500, str(e))

    def handle_create_regis_record(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode('utf-8'))
            fields = data.get('fields', data)
            loai = self.clean(fields.get('Loại đăng ký') or fields.get('loai_dang_ky'))
            account = self.clean(fields.get('Số tài khoản') or fields.get('account_number'))
            phone = self.digits(fields.get('Số điện thoại') or fields.get('phone'))
            customer = self.clean(fields.get('Tên khách hàng') or fields.get('customer_name'))
            staff = self.clean(fields.get('Cán bộ quản lý') or fields.get('can_bo_quan_ly'))
            required_values = [loai, account, customer, staff]
            if loai != 'QR Tài khoản':
                required_values.append(phone)
            if not all(required_values):
                self.send_error_response(400, 'Thiếu trường bắt buộc')
                return
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            if loai != 'QR Tài khoản':
                cursor.execute("""
                    SELECT airtable_id FROM regis_customer_records
                    WHERE so_tai_khoan = %s AND loai_dang_ky = %s
                    LIMIT 1
                """, (account, loai))
                if cursor.fetchone():
                    cursor.close(); conn.close()
                    self.send_error_response(409, f'Số tài khoản {account} đã đăng ký "{loai}" rồi.')
                    return
            cursor.execute("""
                INSERT INTO regis_customer_records (
                    airtable_id, airtable_created_time, loai_dang_ky, so_tai_khoan,
                    so_dien_thoai, ten_khach_hang, can_bo_quan_ly, ghi_chu,
                    ten_chu_ho, so_cccd, ngay_cap, noi_cap, dia_chi,
                    yeu_cau_in_mau_bieu, raw_fields
                ) VALUES (
                    'pg_' || md5(random()::text || clock_timestamp()::text), CURRENT_TIMESTAMP,
                    %s, %s, %s, %s, %s, %s, %s, %s, NULLIF(%s, '')::date, %s, %s, %s, %s
                )
                RETURNING *
            """, (
                loai, account, phone, customer, staff,
                self.clean(fields.get('Ghi chú') or fields.get('ghi_chu')),
                self.clean(fields.get('Tên chủ hộ') or fields.get('ten_chu_ho')),
                self.digits(fields.get('Số CCCD') or fields.get('so_cccd')),
                self.clean(fields.get('Ngày cấp') or fields.get('ngay_cap')),
                self.clean(fields.get('Nơi cấp') or fields.get('noi_cap')),
                self.clean(fields.get('Địa chỉ') or fields.get('dia_chi')),
                self.clean(fields.get('Yêu cầu in mẫu biểu')) or 'Không',
                Json(fields),
            ))
            row = dict(cursor.fetchone())
            conn.commit(); cursor.close(); conn.close()
            logger.info(f"Created regis record {row['airtable_id']} for {customer}")
            self.send_json_response(row_to_airtable_shape(row), status=201)
        except json.JSONDecodeError:
            self.send_error_response(400, "Invalid JSON")
        except Exception as e:
            logger.error(f"Error creating regis record: {e}")
            self.send_error_response(500, str(e))

    @staticmethod
    def clean(value):
        if value is None:
            return ''
        return ' '.join(str(value).strip().split())

    @staticmethod
    def digits(value):
        if value is None:
            return ''
        return ''.join(ch for ch in str(value) if ch.isdigit())

    def send_json_response(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def send_error_response(self, status, message):
        self.send_json_response({'error': message}, status=status)

    def log_message(self, format, *args):
        logger.info(f"{self.address_string()} - {format % args}")


def main():
    logger.info(f"Starting QR/Loa Registration Server on {HOST}:{PORT}")
    if not init_database():
        return 1
    try:
        server = ThreadingHTTPServer((HOST, PORT), RequestHandler)
        logger.info(f"Server running at http://{HOST}:{PORT}/")
        logger.info(f"Serving files from: {PUBLIC_DIR}")
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        return 0
    except Exception as e:
        logger.error(f"Server error: {e}")
        return 1


if __name__ == '__main__':
    exit(main())
