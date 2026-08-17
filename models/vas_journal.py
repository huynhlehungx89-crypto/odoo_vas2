# -*- coding: utf-8 -*-
from odoo import api, fields, models


JOURNAL_SEEDS = [
    # code, name, type, sequence_xml_suffix, prefix
    ('BH', 'Sổ nhật ký bán hàng', 'sale', 'bh', 'BH'),
    ('MH', 'Sổ nhật ký mua hàng', 'purchase', 'mh', 'MH'),
    ('THU', 'Sổ quỹ tiền mặt 111', 'cash', 'thu', 'THU'),
    ('NH', 'Sổ tiền gửi ngân hàng 112', 'bank', 'nh', 'NH'),
    ('KHO', 'Sổ nhật ký kho', 'stock', 'kho', 'KHO'),
    ('LUONG', 'Sổ nhật ký lương', 'payroll', 'luong', 'LUONG'),
    ('TH', 'Sổ nhật ký chung', 'general', 'th', 'TH'),
    ('KC', 'Sổ kết chuyển cuối kỳ', 'closing', 'kc', 'KC'),
    ('MOSO', 'Sổ mở sổ / số dư đầu kỳ', 'opening', 'moso', 'MOSO'),
]


class VasJournal(models.Model):
    _name = 'vas.journal'
    _description = 'Sổ nhật ký VAS'
    _order = 'code'
    _rec_names_search = ['name', 'code']

    code = fields.Char(string='Mã', required=True, index=True, size=16)
    name = fields.Char(string='Tên', required=True)
    type = fields.Selection(
        selection=[
            ('sale', 'Sổ bán hàng'),
            ('purchase', 'Sổ mua hàng'),
            ('cash', 'Tiền mặt'),
            ('bank', 'Ngân hàng'),
            ('stock', 'Kho'),
            ('payroll', 'Lương'),
            ('general', 'Tổng hợp'),
            ('opening', 'Mở sổ'),
            ('closing', 'Kết chuyển'),
        ],
        string='Loại sổ',
        required=True,
    )
    regime_id = fields.Many2one(
        'vas.regime',
        string='Chế độ kế toán',
        required=True,
        index=True,
        ondelete='restrict',
    )
    sequence_id = fields.Many2one(
        'ir.sequence',
        string='Trình tự số chứng từ',
        copy=False,
        help='Sequence used to number vas.move documents.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )

    _code_company_uniq = models.Constraint(
        'UNIQUE(company_id, code)',
        'The journal code must be unique per company.',
    )

    @api.model
    def _ensure_journals_for_company(self, company):
        """Idempotent: đủ sổ TT133 (gồm KC) cho một công ty."""
        company.ensure_one()
        regime = company.vas_regime_id or self.env.ref('connecta_vas.vas_regime_tt133')
        Sequence = self.env['ir.sequence']
        for code, name, jtype, suffix, prefix in JOURNAL_SEEDS:
            journal = self.search([
                ('code', '=', code),
                ('company_id', '=', company.id),
            ], limit=1)
            if journal:
                continue
            seq = Sequence.create({
                'name': 'VAS %s (%s) — %s' % (name, code, company.name),
                'code': 'vas.journal.%s.%s' % (suffix, company.id),
                'prefix': '%s/%%(year)s/' % prefix,
                'padding': 4,
                'company_id': company.id,
            })
            self.create({
                'code': code,
                'name': name,
                'type': jtype,
                'regime_id': regime.id,
                'sequence_id': seq.id,
                'company_id': company.id,
            })
        return True

    @api.model
    def _connecta_seed_tt133_journals(self):
        """Idempotent seed of dedicated TT133 journals + sequences for main company."""
        company = self.env.ref('base.main_company')
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        Sequence = self.env['ir.sequence']
        Imd = self.env['ir.model.data']
        for code, name, jtype, suffix, prefix in JOURNAL_SEEDS:
            seq_xmlid = f'connecta_vas.seq_vas_journal_{suffix}'
            seq = self.env.ref(seq_xmlid, raise_if_not_found=False)
            if not seq:
                seq = Sequence.search([
                    ('code', '=', f'vas.journal.{suffix}'),
                    ('company_id', '=', company.id),
                ], limit=1)
            if not seq:
                seq = Sequence.create({
                    'name': f'VAS {name} ({code})',
                    'code': f'vas.journal.{suffix}',
                    'prefix': f'{prefix}/%(year)s/',
                    'padding': 4,
                    'company_id': company.id,
                })
            Imd._update_xmlids([{
                'xml_id': seq_xmlid,
                'record': seq,
                'noupdate': True,
            }])

            journal_xmlid = f'connecta_vas.vas_journal_{suffix}'
            journal = self.env.ref(journal_xmlid, raise_if_not_found=False)
            if not journal:
                journal = self.search([
                    ('code', '=', code),
                    ('company_id', '=', company.id),
                ], limit=1)
            if not journal:
                journal = self.create({
                    'code': code,
                    'name': name,
                    'type': jtype,
                    'regime_id': regime.id,
                    'sequence_id': seq.id,
                    'company_id': company.id,
                })
            else:
                vals = {}
                if not journal.sequence_id:
                    vals['sequence_id'] = seq.id
                if journal.regime_id != regime:
                    vals['regime_id'] = regime.id
                if vals:
                    journal.write(vals)
            Imd._update_xmlids([{
                'xml_id': journal_xmlid,
                'record': journal,
                'noupdate': True,
            }])
        return True
