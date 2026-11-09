import requests
URL_IPINFO='https://ipinfo.io/'

def get_location(ip):
        response = requests.get(URL_IPINFO+'/' + ip + '/json')
        if response.status_code == 200: #200 ca veut dire ok
                return response.json()

if __name__ == "__main__":
      print(get_location('45.156.87.204'))