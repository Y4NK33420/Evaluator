import subprocess, tempfile, os

code = (
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

with tempfile.NamedTemporaryFile(suffix='.py', delete=False, mode='w') as f:
    f.write(code)
    fname = f.name

tests = [
    ('swap_case\nPython 3.10', 'pYTHON 3.10'),
    ('find_second_largest\n10 20 4 45 99 99', '45'),
    ('is_anagram\nListen\nSilent', 'True'),
    ('swap_case\n1', '1'),
    ('is_anagram\nAnagram\nNagaram', 'True'),
    ('find_second_largest\n5', 'None'),
]
for stdin_val, expected in tests:
    r = subprocess.run(['python3', fname], input=stdin_val, capture_output=True, text=True)
    status = 'PASS' if r.stdout.strip() == expected else 'FAIL'
    print(f'{status}: got={repr(r.stdout.strip())} expected={repr(expected)} stderr={repr(r.stderr[:80])}')
os.unlink(fname)
