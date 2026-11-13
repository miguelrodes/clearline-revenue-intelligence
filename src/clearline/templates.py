"""Bounded outreach structures; account facts supply the personalized sentence."""
TEMPLATES={
 'inactive':('Checking current screening needs','Are these supplies still needed, and who handles purchasing now?'),
 'contact_change':('Purchasing contact for screening supplies','Could you confirm the person or team currently responsible for these purchases?'),
 'reduced_volume':('Checking your current screening requirements','Have your purchasing requirements or ordering arrangements changed?'),
 'product_decline':('Screening supplies check-in','Is this product still part of your screening workflow?'),
 'reorder':('Screening supplies reorder timing','When would it be useful to review your next supply order?'),
 'channel':('Confirming your purchasing route','Are purchases handled directly or through a distributor?'),
 'relationship':('Screening supplies follow-up','Who would be the right person to discuss your current screening requirements?'),
}

def render(strategy,context):
    subject,question=TEMPLATES[strategy]
    return subject,'Hello,\n\n'+context.strip()+'\n\n'+question+'\n\nThank you.'
