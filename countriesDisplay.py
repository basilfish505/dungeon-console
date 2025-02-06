from flask import Flask, render_template
import requests

app = Flask(__name__)

@app.route('/')
def show_countries():
    # Fetch countries from REST Countries API
    response = requests.get('https://restcountries.com/v3.1/all')
    countries = []
    if response.status_code == 200:
        # Get country data and sort by name
        countries = response.json()
        countries.sort(key=lambda x: x['name']['common'])
        # Format population with commas
        for country in countries:
            country['population'] = "{:,}".format(country['population'])
    return render_template('countries.html', countries=countries)

if __name__ == '__main__':
    app.run(debug=True)

