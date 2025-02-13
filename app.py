from flask import Flask, render_template, request,jsonify, redirect, url_for, session, flash
import pandas as pd
import plotly.express as px
import plotly.io as pio
import plotly.graph_objects as go
import matplotlib.pyplot as plt
import time
import numpy as np
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
master_password = "pxllc01"
app.config['SECRET_KEY'] = 'pxllc01'


@app.route("/CalEnegy")
def home():
    return render_template("index.html")

@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form['password']
        if password == master_password:
            session['logged_in'] = True
            flash(f"Welcome, logging in...")
            return redirect(url_for('home'))

        else:
            error = "Incorrect password. Please try again."

    return render_template('login.html', app_title= "CalEnergy", error=error)


@app.route("/calculate", methods=["POST"])
def Calculate():
    if request.method == "POST":
        try:
            start_time = time.time()
            # Retrieve uploaded files
            production_file = request.files.get("file_production")
            file_retrieval_end = time.time()
            print(f"File retrieval time: {file_retrieval_end - start_time:.4f} seconds")

            processing_start = time.time()
            with ThreadPoolExecutor() as executor:
                future = executor.submit(process_production_file, production_file)
                jan_data, may_data = future.result()
            processing_end = time.time()
            print(f"File processing time: {processing_end - processing_start:.4f} seconds")

            # Detect dips for January and May
            dip_detection_start = time.time()

            jan_total_energy_lost = detect_dips(jan_data, "January")
            may_total_energy_lost = detect_dips(may_data, "May")
            dip_detection_end = time.time()
            print(f"Dip detection time: {dip_detection_end - dip_detection_start:.4f} seconds")



            required_columns = ['total_production', 'sitetime']
            for data, name in zip([jan_data, may_data], ['January', 'May']):
                for col in required_columns:
                    if col not in data:
                        raise KeyError(f"Column '{col}' missing in {name} production data.")

            # Generate Energy Lost Graph
            energy_lost_graph = generate_energy_lost_graph(jan_data, may_data)

            # Return the graphs as JSON response
            response = jsonify({
                'production': generate_graph(jan_data, may_data, "Production"),
                'combined1':  generate_combined_graph(
                    jan_data,
                    "January Combined Metrics",
                    {
                        "production": "orange",
                        "moving_average": "green",
                        "deviation_tag_with_time": "red"
                    },
                ),
                'combined2': generate_combined_graph(
                    may_data,
                    "May Combined Metrics",
                    {
                        "production": "blue",
                        "moving_average": "purple",
                        "deviation_tag_with_time": "pink"
                    },
                ),
                'energy1': jan_total_energy_lost,
                'energy2': may_total_energy_lost,
                'energy_lost1': energy_lost_graph["january"],
                'energy_lost2': energy_lost_graph["may"],
                
            })
            total_end_time = time.time()
            print(f"Total execution time: {total_end_time - start_time:.4f} seconds")
            return response
        except Exception as e:
            return jsonify({"error": str(e)}), 400


def process_production_file(file):
    # Step 1: Read the file
    try:
        df = pd.read_csv(file)
    except Exception as e:
        raise ValueError(f"Error reading file: {str(e)}")

    # Step 2: Check if the dataframe is empty
    if df.empty:
        raise ValueError("The uploaded file is empty.")

    # Step 3: Identify energy columns dynamically
    energy_columns = [col for col in df.columns if "dci" in col and "/5min" in col]
    if not energy_columns:
        raise ValueError("No valid energy production columns found.")

    # Step 4: Calculate total production
    df["total_production"] = df[energy_columns].sum(axis=1)

    system_voltage = 1500  # volts
    time_interval_hours = 5 / 60  # 5-minute intervals

    df["total_production_kwh"] = (df["total_production"] * system_voltage / 1000) * time_interval_hours
    df["sitetime"] = pd.to_datetime(df["sitetime"], errors="coerce")
    df.dropna(subset=["sitetime"], inplace=True)

    # Constants
    WF = 10000  # Threshold for moving average condition
    WH = 0.8    # Relative threshold for deviation
    weight_constant = 0.85  # Smoothing factor for EMA

    # Step 5: Calculate Moving Average
    df["moving_average"] = 0.0
    for i in range(len(df)):
        if i == 0:
            if df.loc[i, "total_production"] < WF:
                df.loc[i, "moving_average"] = 0
            else:
                df.loc[i, "moving_average"] = df.loc[i, "total_production"] * (1 - weight_constant)
        else:
            if df.loc[i, "total_production"] < WF:
                df.loc[i, "moving_average"] = 0
            else:
                df.loc[i, "moving_average"] = (
                    df.loc[i - 1, "moving_average"] * weight_constant
                    + df.loc[i, "total_production"] * (1 - weight_constant)
                )

    # Step 6: Calculate Deviation Tag
    df["deviation_tag"] = df.apply(
        lambda row: 1 if (
            row["moving_average"] != 0 and
            row["total_production"] < WH * row["moving_average"]
        ) else 0,
        axis=1
    )

    # Step 7: Calculate Deviation Tag with Time
    df["deviation_tag_with_time"] = df.apply(
        lambda row: row["deviation_tag"] if (row["sitetime"].hour > 10 and row["sitetime"].hour < 15) else 0,
        axis=1
    )

    # df["deviation_tag_with_time"] = df["deviation_tag_with_time"] * df["total_production"].max() * 0.1  # Adjust scale


    # Step 8: Calculate Energy Lost
    df["energy_lost"] = df.apply(
        lambda row: (row["moving_average"] - row["total_production"]) * time_interval_hours
        if row["deviation_tag_with_time"] == 1 and (row["moving_average"] - row["total_production"]) > 0 else 0,
        axis=1
    )

    # Step 9: Filter data for January and May
    jan_data = df[df["sitetime"].dt.month == 1]
    may_data = df[df["sitetime"].dt.month == 5]

    return jan_data, may_data


def detect_dips(data, month_name):
    # Initialize variables to track dips
    dips = []
    ongoing_dip = False
    dip_start = None
    dip_energy_lost = 0
    WH = 0.8  # Relative threshold for significant deviations

    for i in range(len(data)):
        current_time = data.iloc[i]["sitetime"]
        current_total_production = data.iloc[i]["total_production"]
        current_moving_average = data.iloc[i]["moving_average"]
        deviation_tag_with_time = data.iloc[i]["deviation_tag_with_time"]  # Updated to use deviation_tag_with_time

        # Restrict to time window of 10 AM to 3 PM
        if current_time.hour < 10 or current_time.hour >= 15:
            continue
        else:
            # Use the same deviation tag logic from process_production_file
            if (
                current_moving_average != 0 and
                deviation_tag_with_time == 1  # Updated condition
            ):
                if not ongoing_dip:
                    # Start a new dip
                    dip_start = current_time
                    ongoing_dip = True

                # Accumulate energy lost using the same formula from process_production_file
                dip_energy_lost += abs(current_total_production - current_moving_average) * (5 / 60)
            else:
                if ongoing_dip:
                    # End the dip
                    dip_end = current_time
                    dip_duration = (dip_end - dip_start).total_seconds() / 60  # Duration in minutes

                    dips.append({
                        "start_time": dip_start,
                        "end_time": dip_end,
                        "energy_lost": dip_energy_lost,
                        "duration_minutes": dip_duration,
                    })

                    # Reset dip tracking variables
                    ongoing_dip = False
                    dip_energy_lost = 0

    # Capture any ongoing dip at the end of the loop
    if ongoing_dip:
        dip_end = data.iloc[-1]["sitetime"]
        dip_duration = (dip_end - dip_start).total_seconds() / 60
        dips.append({
            "start_time": dip_start,
            "end_time": dip_end,
            "energy_lost": dip_energy_lost,
            "duration_minutes": dip_duration,
        })

    # Calculate total energy lost during dips
    total_energy_lost = sum(dip["energy_lost"] for dip in dips)
    return total_energy_lost


# Graph Generation Functions

def generate_graph(df_jan, df_may, title):
    fig_jan = px.line(
        df_jan, x="sitetime", y="total_production",
        title=f"{title} - January", labels={"sitetime": "Time", "total_production": "Total Production (w)"}
    )
    fig_may = px.line(
        df_may, x="sitetime", y="total_production",
        title=f"{title} - May", labels={"sitetime": "Time", "total_production": "Total Production (w)"}
    )
    return {
        "january": pio.to_html(fig_jan, full_html=False),
        "may": pio.to_html(fig_may, full_html=False)
    }


def generate_combined_graph(data, title, color_map):
    try:
        fig = go.Figure()

        # Add production trace
        fig.add_trace(go.Scatter(
            x=data['sitetime'], 
            y=data['total_production'], 
            mode='lines',
            name=f"{title} Total Production (W)",
            line=dict(color=color_map["production"])
        ))

        # Add moving average trace
        fig.add_trace(go.Scatter(
            x=data['sitetime'], 
            y=data['moving_average'], 
            mode='lines',
            name=f"{title} Moving Average",
            line=dict(color=color_map["moving_average"], dash='dot')
        ))

        # Add deviation trace
        fig.add_trace(go.Scatter(
            x=data['sitetime'], 
            y=data['deviation_tag_with_time'] * max(data['total_production']),  
            mode='lines',
            name=f"{title} deviation_tag_with_time",
            line=dict(color=color_map["deviation_tag_with_time"], width=2, dash='solid')
        ))

        # Update layout for better zoom and scaling
        fig.update_layout(
            title=title,
            xaxis=dict(
                title='Time',
                rangeslider=dict(visible=True),  # Enable range slider
                type='date',  # Ensure proper time scale
            ),
            yaxis=dict(
                title='Energy (W)',
            ),
            legend=dict(title="Metrics"),
            template="plotly_white",
        )

        # Convert Plotly figure to HTML
        return pio.to_html(fig, full_html=False)

    except Exception as e:
        return f"Error generating graph: {e}"

def generate_energy_lost_graph(jan_data, may_data):
    # Filter data for 10 AM to 3 PM
    jan_filtered = jan_data[(jan_data['sitetime'].dt.hour >= 10) & (jan_data['sitetime'].dt.hour < 15)]
    may_filtered = may_data[(may_data['sitetime'].dt.hour >= 10) & (may_data['sitetime'].dt.hour < 15)]

    # Create Plotly line charts for energy lost
    fig_jan = px.line(
        jan_filtered, 
        x="sitetime", 
        y="energy_lost", 
        title="January Energy Lost", 
        labels={"sitetime": "Time", "energy_lost": "Energy Lost (W)"}
    )
    fig_may = px.line(
        may_filtered, 
        x="sitetime", 
        y="energy_lost", 
        title="May Energy Lost", 
        labels={"sitetime": "Time", "energy_lost": "Energy Lost (W)"}
    )

    # Convert figures to HTML
    return {
        'january': pio.to_html(fig_jan, full_html=False),
        'may': pio.to_html(fig_may, full_html=False),
    }


if __name__ == "__main__":
    app.run(debug=True, port=5000)

