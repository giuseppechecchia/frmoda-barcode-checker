# -*- coding: utf-8 -*-
{
    'name': 'Barcodes checker',
    'summary': 'Check your barcodes easily',
    'description': "Check your barcodes easily trought API",
    'depends': ['base', 'queue_job'],
    'external_dependencies': {
        'python': [
            'checkdigit',
            'requests',
            'validators',
            'cachetools'
        ],
    },
    'data': [
        # product.product:
        'views/product_view.xml',

        # Security:
        'security/ir.model.access.csv',
    ],
    'author': 'Giuseppe Checchia',
    'support': 'giuseppechecchia@gmail.com',
    'auto_install': True,
    'application': False,
    'installable': True
}
