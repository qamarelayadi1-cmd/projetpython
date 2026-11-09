import gzip
import os
from pathlib import Path
""""
Read from data all files
in:data [directory]
out:list of rows
"""
def to_rows(path:list):
    data_dir = Path(path)

    try:
        files = os.listdir(data_dir)
    except Exception as e:
        print(path + ' error')
    try:
      
        for file in files:
            file_path=data_dir / file
            if file.endswith('.gz'):
                open_type=gzip.open(file_path,mode='rt') if file.endswith('.gz') else open(file_path)  #operqteur terner
            with open_type as f:
                return f.readlines()

    except FileNotFoundError as e:
        print(e)
        return
    
if __name__ == "__main__":
   data=to_rows('./data')
   if data:
       print(data[:10])
            