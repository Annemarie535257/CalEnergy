from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
import pandas as pd
import plotly.express as px
import plotly.io as pio
import plotly.graph_objects as go
from flask_sqlalchemy import SQLAlchemy
import os

app = Flask(__name__)
master_password = "pxllc01"
app.config['SECRET_KEY'] = 'pxllc01'

# Database configuration
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'calenergy.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Define the database model
class ProductionData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sitetime = db.Column(db.DateTime, nullable=False)
    total_production = db.Column(db.Float, nullable=False)
    moving_average = db.Column(db.Float, nullable=True)
    deviation_tag = db.Column(db.Integer, nullable=True)
    deviation_tag_with_time = db.Column(db.Integer, nullable=True)
    energy_lost = db.Column(db.Float, nullable=True)

    # Dynamically add columns for each energy data
    def __init__(self, sitetime, total_production, moving_average, deviation_tag, deviation_tag_with_time, energy_lost, **kwargs):
        self.sitetime = sitetime
        self.total_production = total_production
        self.moving_average = moving_average
        self.deviation_tag = deviation_tag
        self.deviation_tag_with_time = deviation_tag_with_time
        self.energy_lost = energy_lost
        for key, value in kwargs.items():
            setattr(self, key, value)

# Initialize the database
with app.app_context():
    db.create_all()

def process_production_file(file):
    try:
        df = pd.read_csv(file)

        if df.empty:
            raise ValueError("The uploaded file is empty.")

        df["sitetime"] = pd.to_datetime(df["sitetime"], errors="coerce")
        df.dropna(subset=["sitetime"], inplace=True)

        # Identify energy columns dynamically
        energy_columns = [col for col in df.columns if "dci" in col and "/5min" in col]
        if not energy_columns:
            raise ValueError("No valid energy production columns found.")

        df["total_production"] = df[energy_columns].sum(axis=1)

        system_voltage = 1500  # volts
        time_interval_hours = 5 / 60  # 5-minute intervals

        df["total_production_kwh"] = (df["total_production"] * system_voltage / 1000) * time_interval_hours

        # Calculate moving average
        WF = 10000  # Threshold for moving average condition
        WH = 0.8    # Relative threshold for deviation
        weight_constant = 0.85  # Smoothing factor for EMA

        df["moving_average"] = df["total_production"].ewm(span=5, adjust=False).mean()

        # Calculate deviation tag
        df["deviation_tag"] = df.apply(
            lambda row: 1 if row["total_production"] < WH * row["moving_average"] else 0,
            axis=1
        )

        df["deviation_tag_with_time"] = df.apply(
            lambda row: row["deviation_tag"] if 10 <= row["sitetime"].hour < 15 else 0,
            axis=1
        )

        df["energy_lost"] = df.apply(
            lambda row: (row["moving_average"] - row["total_production"]) * time_interval_hours
            if row["deviation_tag_with_time"] == 1 and row["moving_average"] > row["total_production"] else 0,
            axis=1
        )

        # Store data into database
        for _, row in df.iterrows():
            record = ProductionData(
                sitetime=row["sitetime"],
                total_production=row["total_production"],
                moving_average=row["moving_average"],
                deviation_tag=row["deviation_tag"],
                deviation_tag_with_time=row["deviation_tag_with_time"],
                energy_lost=row["energy_lost"],
                **{col: row[col] for col in energy_columns}
            )
            db.session.add(record)

        db.session.commit()

        jan_data = df[df["sitetime"].dt.month == 1]
        may_data = df[df["sitetime"].dt.month == 5]

        return jan_data, may_data

    except Exception as e:
        raise ValueError(f"Error processing file: {str(e)}")

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
            # Retrieve uploaded files
            production_file = request.files.get("file_production")
            # Step 2: Process files
            jan_data, may_data = process_production_file(production_file)
          
            # Detect dips for January and May
            jan_dips, jan_total_energy_lost = detect_dips(jan_data, "January")
            may_dips, may_total_energy_lost = detect_dips(may_data, "May")
           


            required_columns = ['total_production', 'sitetime']
            for data, name in zip([jan_data, may_data], ['January', 'May']):
                for col in required_columns:
                    if col not in data:
                        raise KeyError(f"Column '{col}' missing in {name} production data.")

            # Generate Energy Lost Graph
            energy_lost_graph = generate_energy_lost_graph(jan_data, may_data)

            # Return the graphs as JSON response
            return jsonify({
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
        except Exception as e:
            return jsonify({"error": str(e)}), 400


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
    return dips, total_energy_lost


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

