# -*- coding: utf-8 -*-
from pathlib import Path
from _gen_gtgt_indicators import TT89, TT80, emit

header = '''<?xml version="1.0" encoding="utf-8"?>
<odoo noupdate="1">
    <record id="vas_gtgt_form_01" model="vas.gtgt.form.type">
        <field name="code">01/GTGT</field>
        <field name="name">Tờ khai thuế GTGT (khấu trừ)</field>
    </record>
    <record id="vas_gtgt_version_tt80" model="vas.gtgt.form.version">
        <field name="code">TT80</field>
        <field name="name">Mẫu 01/GTGT theo Thông tư 80/2021/TT-BTC</field>
        <field name="form_type_id" ref="vas_gtgt_form_01"/>
        <field name="circular_label">Thông tư 80/2021/TT-BTC</field>
        <field name="date_start">2016-01-01</field>
        <field name="date_end">2026-06-30</field>
    </record>
    <record id="vas_gtgt_version_tt89" model="vas.gtgt.form.version">
        <field name="code">TT89</field>
        <field name="name">Mẫu 01/GTGT theo Thông tư 89/2026/TT-BTC</field>
        <field name="form_type_id" ref="vas_gtgt_form_01"/>
        <field name="circular_label">Thông tư 89/2026/TT-BTC</field>
        <field name="date_start">2026-07-01</field>
    </record>
    <record id="vas_gtgt_act_sxkd" model="vas.gtgt.activity">
        <field name="code">SXKD</field>
        <field name="name">Hoạt động sản xuất kinh doanh</field>
        <field name="sequence">10</field>
    </record>
    <record id="vas_gtgt_act_dadt" model="vas.gtgt.activity">
        <field name="code">DADT</field>
        <field name="name">Dự án đầu tư</field>
        <field name="sequence">20</field>
    </record>
    <record id="vas_tax_32b" model="vas.tax">
        <field name="code">GTGT_32B</field>
        <field name="name">Không tính vào giá tính thuế GTGT</field>
        <field name="sequence">70</field>
        <field name="regime_id" ref="vas_regime_tt133"/>
        <field name="rate">0</field>
        <field name="tax_scope">output</field>
        <field name="date_start">2026-07-01</field>
        <field name="declaration_value_tag">32b</field>
        <field name="match_mode">rate</field>
        <field name="odoo_name_token">không tính vào giá</field>
    </record>
    <record id="vas_tax_34a" model="vas.tax">
        <field name="code">GTGT_34A</field>
        <field name="name">Không thuộc phạm vi PL thuế GTGT</field>
        <field name="sequence">80</field>
        <field name="regime_id" ref="vas_regime_tt133"/>
        <field name="rate">0</field>
        <field name="tax_scope">output</field>
        <field name="date_start">2026-07-01</field>
        <field name="declaration_value_tag">34a</field>
        <field name="match_mode">rate</field>
        <field name="odoo_name_token">không thuộc phạm vi</field>
    </record>
'''

body = (
    emit('vas_gtgt_version_tt89', TT89, 'ind_tt89')
    + '\n'
    + emit('vas_gtgt_version_tt80', TT80, 'ind_tt80')
)
footer = '\n</odoo>\n'
path = Path(__file__).with_name('vas_gtgt_declaration_seed.xml')
path.write_text(header + body + footer, encoding='utf-8')
print('wrote', path, path.stat().st_size)
