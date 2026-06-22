# backend/database.py

STUDENTS_DB = [
    {
        "student_id": "2024001",
        "full_name": "John Doe",
        "whatsapp": "+254712345678",
        "has_voted": False
    },
    {
        "student_id": "2024002",
        "full_name": "Jane Smith",
        "whatsapp": "+254787654321",
        "has_voted": False
    }
]

# This is what's missing! 
CANDIDATES = [
    {
        "id": 1,
        "name": "Dr. Sarah Kwigira",
        "position": "Guild President",
        "image": "https://api.dicebear.com/7.x/avataaars/svg?seed=Sarah",
        "votes": 0
    },
    {
        "id": 2,
        "name": "Mark Okello",
        "position": "Guild President",
        "image": "https://api.dicebear.com/7.x/avataaars/svg?seed=Mark",
        "votes": 0
    },
    {
        "id": 3,
        "name": "Mercy Anyango",
        "position": "Vice President",
        "image": "https://api.dicebear.com/7.x/avataaars/svg?seed=Mercy",
        "votes": 0
    }
]

active_otps = {}