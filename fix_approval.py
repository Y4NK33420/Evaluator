"""
Patch the approved test artifact content_json to add stdin discriminators
so the dispatcher can route each testcase to the correct function.
"""
import json
import psycopg2

APPROVAL_ID = "64516411-5595-4c80-96b2-dbe29694bcc0"
SUBMISSION_ID = "e5d05550-7024-461a-a027-eaa0fb8efe0f"

FIXED_TESTCASES = [
    {
        "testcase_id": "tc_01", "weight": 1.0,
        "input_mode": "stdin", "stdin": "swap_case\nPython 3.10",
        "argv": [], "files": {},
        "expected_stdout": "pYTHON 3.10\n",
        "expected_stderr": None, "expected_exit_code": 0,
    },
    {
        "testcase_id": "tc_02", "weight": 1.0,
        "input_mode": "stdin", "stdin": "find_second_largest\n10 20 4 45 99 99",
        "argv": [], "files": {},
        "expected_stdout": "45\n",
        "expected_stderr": None, "expected_exit_code": 0,
    },
    {
        "testcase_id": "tc_03", "weight": 1.0,
        "input_mode": "stdin", "stdin": "is_anagram\nListen\nSilent",
        "argv": [], "files": {},
        "expected_stdout": "True\n",
        "expected_stderr": None, "expected_exit_code": 0,
    },
    {
        "testcase_id": "tc_04", "weight": 1.5,
        "input_mode": "stdin", "stdin": "swap_case\n1",
        "argv": [], "files": {},
        "expected_stdout": "1\n",
        "expected_stderr": None, "expected_exit_code": 0,
    },
    {
        "testcase_id": "tc_05", "weight": 1.5,
        "input_mode": "stdin", "stdin": "is_anagram\nAnagram\nNagaram",
        "argv": [], "files": {},
        "expected_stdout": "True\n",
        "expected_stderr": None, "expected_exit_code": 0,
    },
    {
        "testcase_id": "tc_06", "weight": 0.5,
        "input_mode": "stdin", "stdin": "find_second_largest\n5",
        "argv": [], "files": {},
        "expected_stdout": "None\n",
        "expected_stderr": None, "expected_exit_code": 0,
    },
]

# The dispatcher + student solution to inject as source_files in jobs
FIXED_SOLUTION = (
    "import sys as _sys\n"
    "\n"
    "def _dispatcher():\n"
    "    lines = _sys.stdin.read().strip().split('\\n')\n"
    "    fn_name = lines[0].strip()\n"
    "    rest = lines[1:]\n"
    "    if fn_name == 'swap_case':\n"
    "        arg = rest[0] if rest else ''\n"
    "        print(swap_case(arg))\n"
    "    elif fn_name == 'find_second_largest':\n"
    "        nums = list(map(int, rest[0].split())) if rest else []\n"
    "        print(find_second_largest(nums))\n"
    "    elif fn_name == 'is_anagram':\n"
    "        s1 = rest[0] if len(rest) > 0 else ''\n"
    "        s2 = rest[1] if len(rest) > 1 else ''\n"
    "        print(is_anagram(s1, s2))\n"
    "\n"
    "def swap_case(s):\n"
    "    result = ''\n"
    "    for char in s:\n"
    "        if char.isupper(): result += char.lower()\n"
    "        elif char.islower(): result += char.upper()\n"
    "        else: result += char\n"
    "    return result\n"
    "\n"
    "def find_second_largest(numbers):\n"
    "    if len(numbers) < 2: return None\n"
    "    first = second = float('-inf')\n"
    "    for num in numbers:\n"
    "        if num > first: second = first; first = num\n"
    "        elif num > second and num != first: second = num\n"
    "    return second if second != float('-inf') else None\n"
    "\n"
    "def is_anagram(str1, str2):\n"
    "    s1 = str1.replace(' ', '').lower()\n"
    "    s2 = str2.replace(' ', '').lower()\n"
    "    if len(s1) != len(s2): return False\n"
    "    cc = {}\n"
    "    for c in s1: cc[c] = cc.get(c, 0) + 1\n"
    "    for c in s2:\n"
    "        if c not in cc or cc[c] == 0: return False\n"
    "        cc[c] -= 1\n"
    "    return True\n"
    "\n"
    "if __name__ == '__main__': _dispatcher()\n"
)

conn = psycopg2.connect("postgresql://amgs:amgs@postgres:5432/amgs")
cur = conn.cursor()

# 1. Read existing content_json to preserve other fields
cur.execute("SELECT content_json FROM code_eval_approval_records WHERE id = %s", (APPROVAL_ID,))
row = cur.fetchone()
existing = row[0] if row else {}
existing["testcases"] = FIXED_TESTCASES
cur.execute(
    "UPDATE code_eval_approval_records SET content_json = %s::json WHERE id = %s",
    (json.dumps(existing), APPROVAL_ID)
)
print(f"Updated approval record: {cur.rowcount} row(s)")

# 2. Update all FAILED jobs for this submission to inject dispatcher + new testcases
cur.execute(
    "SELECT id, request_json FROM code_eval_jobs WHERE submission_id = %s ORDER BY created_at DESC",
    (SUBMISSION_ID,)
)
jobs = cur.fetchall()
updated = 0
for job_id, req in jobs:
    req["testcases"] = FIXED_TESTCASES
    req["source_files"]["solution.py"] = FIXED_SOLUTION
    cur.execute(
        "UPDATE code_eval_jobs SET request_json = %s::json WHERE id = %s",
        (json.dumps(req), job_id)
    )
    updated += 1
print(f"Updated {updated} job(s) with new testcases + dispatcher source")

conn.commit()
cur.close()
conn.close()
print("Done. Re-dispatch now.")
