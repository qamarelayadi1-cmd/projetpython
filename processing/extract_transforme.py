import re 
"""
in:list of rows
out:datetTime,ip,country,Succes,Failed,Invalid user for sshd service

"""
pattern=re.compile(r'(?P<month>\w{3}\s+(?P<day>\d{1,2}\s+(?P<time>\d{2}:\d{2}:\d{2}))\s+(?P<server>\w+)\s+(?P<service>\w+)\[.+:'\s+(?P<message>.+))')
def extract_from_row(row):
 match=re.search(pattern,row):
  if match:
   print(match.groupdict())
 return None
 