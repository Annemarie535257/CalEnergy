from flask import Flask, render_template, request,jsonify
import pandas as pd
import plotly.express as px
import plotly.io as pio
import plotly.graph_objects as go
import matplotlib.pyplot as plt

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/calculate", methods=["POST"])
def Calculate():
    if request.method == "POST":
        try:
            # Retrieve uploaded files
            production_file = request.files.get("file_production")
            revenue_file1 = request.files.get("file_revenue1")
            revenue_file2 = request.files.get("file_revenue2")

            # Step 1: Validate file uploads
            if not (production_file and revenue_file1 and revenue_file2):
                return "Error: Please upload all required files (production, revenue1, revenue2)."

            # Step 2: Process files
            jan_data, may_data = process_production_file(production_file)
            revenue_jan = process_revenue_file(revenue_file1)
            revenue_may = process_revenue_file(revenue_file2)

            # Detect dips for January and May
            jan_dips, jan_total_energy_lost = detect_dips(jan_data, "January")
            may_dips, may_total_energy_lost = detect_dips(may_data, "May")


            required_columns = ['total_production', 'sitetime']
            for data, name in zip([jan_data, may_data], ['January', 'May']):
                for col in required_columns:
                    if col not in data:
                        raise KeyError(f"Column '{col}' missing in {name} production data.")

            revenue_columns = ['Exported Energy (kWh)']
            for data, name in zip([revenue_jan, revenue_may], ['January', 'May']):
                for col in revenue_columns:
                    if col not in data:
                        raise KeyError(f"Column '{col}' missing in {name} revenue data.")

            system_voltage = 1500  # volts
            time_interval_hours = 5 / 60  # 5-minute intervals

            # Convert production data
            jan_data_converted = (jan_data['total_production'] * system_voltage * time_interval_hours) / 1000
            july_data_converted = (may_data['total_production'] * system_voltage * time_interval_hours) / 1000

            # Extract exported energy
            revenue_jan_export = revenue_jan['Exported Energy (kWh)']
            revenue_july_export = revenue_may['Exported Energy (kWh)']

            # Align indices to prevent duplication or misalignment
            jan_data_converted = jan_data_converted.reset_index(drop=True)
            revenue_jan_export = revenue_jan_export.reset_index(drop=True)
            july_data_converted = july_data_converted.reset_index(drop=True)
            revenue_july_export = revenue_july_export.reset_index(drop=True)

            # Subtract revenue from production
            jan_total_data = jan_data_converted - revenue_jan_export
            july_total_data = july_data_converted - revenue_july_export

            # Concatenate sitetime with results
            index_column_jan = jan_data['sitetime'].reset_index(drop=True)
            index_column_july = may_data['sitetime'].reset_index(drop=True)

            jan_total_data_full = pd.concat([index_column_jan, jan_total_data], axis=1)
            jan_total_data_full.columns = ['sitetime', 'Net Production (kWh)']
            july_total_data_full = pd.concat([index_column_july, july_total_data], axis=1)
            july_total_data_full.columns = ['sitetime', 'Net Production (kWh)']

            jan_diff = pd.concat([jan_data['sitetime'].reset_index(drop=True), jan_total_data], axis=1)
            jan_diff.columns = ['sitetime', 'Net Production (kWh)']

            may_diff = pd.concat([may_data['sitetime'].reset_index(drop=True), july_total_data], axis=1)
            may_diff.columns = ['sitetime', 'Net Production (kWh)']

            # Step 4: Generate graphs
            graphs = {
                "production": generate_graph(jan_data, may_data, "Production"),
                "revenue1": generate_revenue_graph(revenue_jan, "Revenue Meter (January)"),
                "revenue2": generate_revenue_graph(revenue_may, "Revenue Meter (May)"),
                "difference": generate_difference_graph(jan_total_data_full, july_total_data_full, "Production vs Revenue Difference"),
                "combined_jan": generate_combined_graph(
                    jan_data,
                    "January Combined Metrics",
                    {
                        "production": "orange",
                        "moving_average": "green",
                        "deviation": "red"
                    }
                ),
                "combined_may": generate_combined_graph(
                    may_data,
                    "May Combined Metrics",
                    {
                        "production": "blue",
                        "moving_average": "purple",
                        "deviation": "pink"
                    }
                ),
            }

            # Return the graphs as JSON response
            return jsonify({
                'production': graphs['production'],
                'revenue1': graphs['revenue1'],
                'revenue2': graphs['revenue2'],
                'difference': graphs['difference'],
                'combined1': graphs['combined_jan'],
                'combined2': graphs['combined_may'],
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 400


# Production File Processing Functions

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

    # Step 5: Implement Exponential Moving Average (EMA)
    weight_constant = 0.75  # Weight for EMA (equivalent to $WD$1 in Excel)
    threshold_factor = 0.75  # Threshold for significant deviation (equivalent to $WF$1 in Excel)

    # Initialize EMA column
    df["moving_average"] = 0.0

    # Set the first value of EMA to the first total production value
    if not df.empty:
        df.loc[0, "moving_average"] = df.loc[0, "total_production"]

    # Calculate EMA iteratively
    for i in range(1, len(df)):
        df.loc[i, "moving_average"] = (
            df.loc[i - 1, "moving_average"] * weight_constant
            + df.loc[i, "total_production"] * (1 - weight_constant)
        )

    # Step 6: Calculate Deviation
    df["deviation"] = df["total_production"] - df["moving_average"]

    # Step 7: Flag Deviations Based on Relative Threshold
    df["deviation_tag"] = df.apply(
        lambda row: 1 if (row["moving_average"] != 0 and row["total_production"] < threshold_factor * row["moving_average"]) else 0,
        axis=1
    )

    # Step 8: Calculate Energy Lost
    df["energy_lost"] = df.apply(
        lambda row: abs(row["deviation"]) * (5 / 60) if row["deviation_tag"] == 1 else 0,
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

    for i in range(len(data)):
        current_time = data.iloc[i]["sitetime"]
        current_total_production = data.iloc[i]["total_production"]
        current_moving_average = data.iloc[i]["moving_average"]
        deviation_tag = data.iloc[i]["deviation_tag"]

        # Restrict to time window of 10 AM to 3 PM
        if current_time.hour < 10 or current_time.hour >= 15:
            continue

        # Use deviation tag to determine if this row contributes to a dip
        if deviation_tag == 1:
            if not ongoing_dip:
                # Start a new dip
                dip_start = current_time
                ongoing_dip = True

            # Calculate energy lost using the same formula from `process_production_file`
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

    # Print dip details
    print(f"\n{month_name} Dips (10 AM to 3 PM):")
    print(f"Total Dips Detected: {len(dips)}")
    for dip in dips:
        print(f"- Dip from {dip['start_time']} to {dip['end_time']} (Duration: {dip['duration_minutes']} mins): Energy Lost = {dip['energy_lost']} kWh")

    print(f"Total Energy Lost in {month_name}: {total_energy_lost} kWh\n")

    return dips, total_energy_lost


# Function to process revenue file
def process_revenue_file(file):
    # Step 1: Read the file content
    try:
        df = pd.read_csv(file, skiprows=5)
        # print(f"File read successfully. Shape of dataframe: {df.shape}")
    except Exception as e:
        raise ValueError(f"Error reading file: {str(e)}")
    
    # Step 2: Check for required columns
    # print("Validating required columns in DataFrame...")
    required_columns = ["Date Time", "Export kWh"]
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing columns: {', '.join(missing_columns)}")
    # print("All required columns are present.")

    # Step 3: Rename columns for consistency
    # print("Renaming columns for consistency...")
    df.rename(columns={"Date Time": "Time", "Export kWh": "Exported Energy (kWh)"}, inplace=True)
    # print("Renaming complete. Here are the first few rows:")
    # print(df.head())

    return df

 

# Graph Generation Functions

def generate_graph(df_jan, df_may, title):
    fig_jan = px.line(
        df_jan, x="sitetime", y="total_production",
        title=f"{title} - January", labels={"sitetime": "Time", "total_production": "Total Production (Kw)"}
    )
    fig_may = px.line(
        df_may, x="sitetime", y="total_production",
        title=f"{title} - May", labels={"sitetime": "Time", "total_production": "Total Production (Kw)"}
    )
    return {
        "january": pio.to_html(fig_jan, full_html=False),
        "may": pio.to_html(fig_may, full_html=False)
    }


def generate_revenue_graph(df, title):
    try:
        # Create a line plot for exported energy
        fig = px.line(
            df,
            x="Time",
            y="Exported Energy (kWh)",
            title=title,
            labels={"Exported Energy (kWh)": "Exported Energy (kWh)", "Time": "Time"}
        )

        # Update layout to show only dates by default and allow zooming
        fig.update_layout(
            xaxis=dict(
                title="Date",
                tickformat="%b %d",  # Show month and day
                rangeslider=dict(visible=True),  # Add a range slider for zooming
            ),
            yaxis=dict(
                title="Exported Energy (kWh)"
            )
        )

        # Update hover data
        fig.update_traces(
            hovertemplate="Time=%{x}<br>Exported Energy=%{y:.2f} kWh"
        )

        # Convert Plotly figure to HTML
        return pio.to_html(fig)

    except Exception as e:
        return f"Error generating graph: {str(e)}"

def generate_difference_graph(jan_diff, may_diff, title):
    try:
        if jan_diff is None or may_diff is None or jan_diff.empty or may_diff.empty:
            raise ValueError("Input data for graphs is missing or empty.")
 
        # print("January Difference Data (Head):")
        # print(jan_diff.head())  # Debug print for January difference data
 
        # Generate graph for January difference
        fig_jan = px.line(
            jan_diff,
            x="sitetime",
            y="Net Production (kWh)",
            title=f"{title} - January",
            labels={"sitetime": "Date",
                    "Net Production (kWh)": "Net Difference (kWh)"}
        )
 
        # Generate graph for May difference
        fig_may = px.line(
            may_diff,
            x="sitetime",
            y="Net Production (kWh)",
            title=f"{title} - May",
            labels={"sitetime": "Date",
                    "Net Production (kWh)": "Net Difference (kWh)"}
        )
 
        return {
            "january": pio.to_html(fig_jan, full_html=False),
            "may": pio.to_html(fig_may, full_html=False),
        }
    except Exception as e:
        # print(f"Error generating difference graph: {e}")
        return {
            "january": f"Error generating January graph: {e}",
            "may": f"Error generating May graph: {e}",
        }

def generate_combined_graph(data, title, color_map):
    try:
        fig = go.Figure()

        # Add production trace
        fig.add_trace(go.Scatter(
            x=data['sitetime'], 
            y=data['total_production'], 
            mode='lines',
            name=f"{title} Total Production (kW)",
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
            y=data['deviation'], 
            mode='markers',
            name=f"{title} Deviation",
            marker=dict(color=color_map["deviation"], size=6)
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
                title='Energy (kW)',
            ),
            legend=dict(title="Metrics"),
            template="plotly_white"
        )

        # Convert Plotly figure to HTML
        return pio.to_html(fig, full_html=False)

    except Exception as e:
        return f"Error generating graph: {e}"

if __name__ == "__main__":
    app.run(debug=True)