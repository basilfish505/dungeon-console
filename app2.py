from flask import Flask, render_template
import requests

app = Flask(__name__)

@app.route('/')
def home():
    # Get list of countries from REST Countries API
    response = requests.get('https://restcountries.com/v3.1/all')
    countries = response.json()
    
    # Sort countries by name
    countries.sort(key=lambda x: x['name']['common'])
    
    return render_template('countries.html', countries=countries)

if __name__ == '__main__':
    app.run(debug=True, port=5001)