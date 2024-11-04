import matplotlib
matplotlib.use('Agg')  # Configura Matplotlib para usar el backend 'Agg'

from flask import Flask, render_template, request, redirect, url_for, send_file
import requests
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
from datetime import datetime, timedelta
from io import BytesIO
import pytz
from timezonefinder import TimezoneFinder  # Añadido para obtener la zona horaria precisa
import os
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()  # Cargar variables de entorno desde .env
API_KEY = os.getenv("API_KEY")
tf = TimezoneFinder()

# Función para obtener coordenadas y zona horaria de una ciudad usando Geocoding
def get_coordinates(city_name):
    url = f'http://api.openweathermap.org/geo/1.0/direct?q={city_name}&limit=1&appid={API_KEY}'
    response = requests.get(url)
    data = response.json()
    if response.status_code == 200 and data:
        lat = data[0]['lat']
        lon = data[0]['lon']
        timezone = tf.timezone_at(lat=lat, lng=lon)
        return lat, lon, timezone, data[0]
    print(f"Error al obtener coordenadas: {response.status_code} {response.text}")
    return None, None, 'UTC', None

# Función para obtener los datos de la API del clima
def get_weather_data(lat, lon):
    url = f'http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={API_KEY}&units=metric&lang=es'
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    print(f"Error al obtener datos del clima: {response.status_code} {response.text}")
    return None

# Función para obtener los datos de la API de UVI actual
def get_current_uvi(lat, lon):
    url = f'http://api.openweathermap.org/data/2.5/uvi?lat={lat}&lon={lon}&appid={API_KEY}'
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    print(f"Error al obtener el índice UV actual: {response.status_code} {response.text}")
    return None

# Función para obtener los datos del pronóstico de UVI
def get_uvi_forecast(lat, lon):
    url = f'http://api.openweathermap.org/data/2.5/uvi/forecast?lat={lat}&lon={lon}&appid={API_KEY}'
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    print(f"Error al obtener el pronóstico de UVI: {response.status_code} {response.text}")
    return None

# Función para convertir timestamps a la hora local
def convert_to_local_time(timestamp, timezone):
    utc_time = datetime.utcfromtimestamp(timestamp).replace(tzinfo=pytz.utc)
    try:
        local_tz = pytz.timezone(timezone)
    except Exception as e:
        print(f"Error al convertir la zona horaria: {e}")
        local_tz = pytz.utc  # Fallback a UTC si la zona horaria no es válida
    return utc_time.astimezone(local_tz)

# Función para generar la gráfica de UV
def create_uv_index_plot(sunrise, sunset, peak_uvi):
    midday_timestamp = (sunrise.timestamp() + sunset.timestamp()) / 2
    midday = datetime.fromtimestamp(midday_timestamp, sunrise.tzinfo)

    std_dev = (sunset - sunrise).total_seconds() / 5
    timestamps = np.linspace(sunrise.timestamp(), sunset.timestamp(), 100)
    uv_values = peak_uvi * np.exp(-0.5 * ((timestamps - midday_timestamp) / std_dev) ** 2)
    times_dt = [datetime.fromtimestamp(t, sunrise.tzinfo) for t in timestamps]

    plt.figure(figsize=(8, 4))
    plt.plot(times_dt, uv_values, label="Índice UV")
    plt.xlabel("Hora del día")
    plt.ylabel("Índice UV")
    plt.title("Índice UV a lo largo del día")
    plt.legend()
    plt.grid()

    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=sunrise.tzinfo))
    plt.gca().xaxis.set_major_locator(mdates.HourLocator(interval=1))
    plt.gcf().autofmt_xdate()

    img = BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    plt.close()
    return img

@app.route('/', methods=['GET', 'POST'])
def index():
    city_name = request.form.get('city') if request.method == 'POST' else 'Madrid'
    lat, lon, timezone, city_info = get_coordinates(city_name)

    if lat is None or lon is None:
        return render_template('index.html', error="No se pudo encontrar la ciudad. Intenta otra vez.")

    weather_data = get_weather_data(lat, lon)
    if weather_data is None:
        return render_template('index.html', error="No se pudo obtener información del clima.")

    current_uvi = get_current_uvi(lat, lon)
    uvi_forecast = get_uvi_forecast(lat, lon)

    try:
        sunrise = convert_to_local_time(weather_data['sys']['sunrise'], timezone)
        sunset = convert_to_local_time(weather_data['sys']['sunset'], timezone)
    except KeyError as e:
        return render_template('index.html', error="Error al obtener información de amanecer/anochecer: " + str(e))

    peak_uvi = current_uvi['value'] if current_uvi else 0
    uv_plot = create_uv_index_plot(sunrise, sunset, peak_uvi)

    dosis_uv = None
    hora_inicio = request.form.get('hora_inicio')
    hora_fin = request.form.get('hora_fin')

    if hora_inicio and hora_fin:
        formato_hora = '%H:%M'
        try:
            inicio_exposicion = datetime.strptime(hora_inicio, formato_hora).replace(
                year=sunrise.year, month=sunrise.month, day=sunrise.day, tzinfo=sunrise.tzinfo
            )
            fin_exposicion = datetime.strptime(hora_fin, formato_hora).replace(
                year=sunset.year, month=sunset.month, day=sunset.day, tzinfo=sunset.tzinfo
            )

            if inicio_exposicion >= sunrise and fin_exposicion <= sunset and inicio_exposicion < fin_exposicion:
                std_dev = (sunset - sunrise).total_seconds() / 5
                midday_timestamp = (sunrise.timestamp() + sunset.timestamp()) / 2

                timestamps = np.linspace(inicio_exposicion.timestamp(), fin_exposicion.timestamp(), 100)
                uv_values = peak_uvi * np.exp(-0.5 * ((timestamps - midday_timestamp) / std_dev) ** 2)
                total_uv_dosis = np.trapz(uv_values, timestamps)

                dosis_uv = round(total_uv_dosis, 2)
            else:
                dosis_uv = "Las horas deben estar entre el amanecer y el anochecer, y la hora de inicio debe ser anterior a la de fin."

        except ValueError as e:
            dosis_uv = f"Formato de hora inválido: {e}"

    return render_template(
        'index.html',
        weather_data=weather_data,
        current_uvi=current_uvi,
        uvi_forecast=uvi_forecast,
        uv_plot_url='/uv_plot',
        city_name=city_name,
        sunrise=sunrise,
        sunset=sunset,
        city_info=city_info,
        dosis_uv=dosis_uv,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin
    )

@app.route('/uv_plot')
def uv_plot():
    city_name = request.args.get('city', 'Madrid')
    lat, lon, timezone, city_info = get_coordinates(city_name)
    if lat is None or lon is None:
        return None

    weather_data = get_weather_data(lat, lon)
    if weather_data is None:
        return None

    current_uvi = get_current_uvi(lat, lon)
    if current_uvi is None:
        return None

    try:
        sunrise = convert_to_local_time(weather_data['sys']['sunrise'], timezone)
        sunset = convert_to_local_time(weather_data['sys']['sunset'], timezone)
    except KeyError as e:
        print(f"Error al obtener amanecer/anochecer en la gráfica: {e}")
        return None

    peak_uvi = current_uvi['value'] if current_uvi else 0

    uv_plot_img = create_uv_index_plot(sunrise, sunset, peak_uvi)
    return send_file(uv_plot_img, mimetype='image/png')

if __name__ == '__main__':
    app.run(debug=True)
