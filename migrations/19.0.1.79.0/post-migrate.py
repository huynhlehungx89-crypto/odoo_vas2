# -*- coding: utf-8 -*-
"""L79: Công nợ hub ready + clear temp debt-offset shortcut."""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE vas_ops_group
           SET state = 'ready',
               temp_action_xmlid = NULL
         WHERE code = 'ar_ap'
        """
    )
