"""Mock member data for the banking portal."""

MEMBERS = {
    "12345": {
        "name": "Alice Johnson",
        "account_type": "Savings",
        "savings": "$15,234.56",
        "checking": "$3,421.00",
        "status": "active",
    },
    "12346": {
        "name": "Bob Smith",
        "account_type": "Checking",
        "savings": "$8,100.00",
        "checking": "$12,555.33",
        "status": "active",
    },
    "12347": {
        "name": "Carol Davis",
        "account_type": "Savings",
        "savings": "$45,000.00",
        "checking": "$1,200.00",
        "status": "active",
    },
    "88888": {
        "name": "Restricted User",
        "account_type": "Savings",
        "savings": "N/A",
        "checking": "N/A",
        "status": "restricted",
    },
    "77777": {
        "name": "Slow User",
        "account_type": "Checking",
        "savings": "$500.00",
        "checking": "$200.00",
        "status": "slow",
    },
}

CREDENTIALS = {
    "admin": "admin123",
}
