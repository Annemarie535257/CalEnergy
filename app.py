from flask import Flask, render_template, request,jsonify
import pandas as pd
import plotly.express as px
import plotly.io as pio
import plotly.graph_objects as go

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
            # print("Validating uploaded files...")
            if not (production_file and revenue_file1 and revenue_file2):
                return "Error: Please upload all required files (production, revenue1, revenue2)."
            # print("All files uploaded successfully.")

            # Step 2: Process files
            jan_data, may_data = process_production_file(production_file)
            revenue_jan = process_revenue_file(revenue_file1)
            revenue_may = process_revenue_file(revenue_file2)

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
            # Print shapes for verification
            # print("January Data Converted Shape:", jan_data_converted.shape)
            # print("July Data Converted Shape:", july_data_converted.shape)
            # print("Revenue January Shape:", revenue_jan_export.shape)
            # print("Revenue July Shape:", revenue_july_export.shape)
            # print("Final January Data Shape:", jan_total_data_full.shape)
            # print("Final July Data Shape:", july_total_data_full.shape)

            # Step 3: Calculate difference
            # jan_diff, may_diff = difference(production_file, revenue_file1, revenue_file2)

            # Step 4: Generate graphs
            graphs = {
                "production": generate_graph(jan_data, may_data, "Production"),
                "revenue1": generate_revenue_graph(revenue_jan, "Revenue Meter (January)"),
                "revenue2": generate_revenue_graph(revenue_may, "Revenue Meter (May)"),
                "difference": generate_difference_graph(jan_total_data_full, july_total_data_full, " Production vs Revenue Difference"),
                "combined_jan": generate_combined_graph(
                    jan_data,
                    revenue_jan,
                    jan_diff,
                    "January Combined Metrics",
                    {"production": "orange", "revenue": "red", "difference": "green"}
                ),
                "combined_may": generate_combined_graph(
                    may_data,
                    revenue_may,
                    may_diff,
                    "May Combined Metrics",
                    {"production": "orange", "revenue": "red", "difference": "green"}
                )
            }
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


def process_production_file(file):
    # Step 2: Read the file content
    try:
        df = pd.read_csv(file)
        # print(f"File read successfully. Shape of dataframe: {df.shape}")
        # print(df.head())
    except Exception as e:
        raise ValueError(f"Error reading file: {str(e)}")
    
    # Step 3: Check if the dataframe is empty
    if df.empty:
        raise ValueError("The uploaded file is empty.")
    # print("DataFrame is not empty. Here are the first few rows:")
    # print(df.head())

    # # Step 4: Identify energy columns dynamically
    # print("Identifying energy production columns...")
    energy_columns = [col for col in df.columns if "dci" in col and "/5min" in col]
    if not energy_columns:
        raise ValueError("No valid energy production columns found.")
    # print(f"Identified energy columns: {energy_columns}")
    
    # Step 5: Calculate total production
    # print("Calculating total production...")
    df["total_production"] = df[energy_columns].sum(axis=1)

    system_voltage = 1500  # volts
    time_interval_hours = 5 / 60  # 5-minute intervals

    df["total_production_kwh"] = (df["total_production"] * system_voltage / 1000) * time_interval_hours
    # print(df.head(2))
    
    df["sitetime"] = pd.to_datetime(df["sitetime"], errors="coerce")
    
    df.dropna(subset=["sitetime"], inplace=True)

    jan_data = df[df["sitetime"].dt.month == 1]

    # print("Filtering data for May...")
    may_data = df[df["sitetime"].dt.month == 5]
    # print(f"May data shape: {may_data.shape}. Sample data:")
    # print(may_data.head())

    # print("Processing completed successfully. Returning January and May data.")
    return jan_data, may_data


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
        df_jan, x="sitetime", y="total_production_kwh",
        title=f"{title} - January", labels={"sitetime": "Time", "total_production_kwh": "Total Production (Kwh)"}
    )
    fig_may = px.line(
        df_may, x="sitetime", y="total_production_kwh",
        title=f"{title} - May", labels={"sitetime": "Time", "total_production_kwh": "Total Production (Kwh)"}
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

def generate_combined_graph(data, revenue, diff, title, color_scheme):

    try:
        # Create a figure
        fig = go.Figure()

        # Add production trace
        fig.add_trace(go.Scatter(
            x=data['sitetime'], 
            y=data['total_production_kwh'], 
            mode='lines',
            name='Total Production (kWh)',
            line=dict(color=color_scheme['production'])
        ))

        # Add revenue trace
        fig.add_trace(go.Scatter(
            x=data['sitetime'], 
            y=revenue['Exported Energy (kWh)'], 
            mode='lines',
            name='Revenue (kWh)',
            line=dict(color=color_scheme['revenue'])
        ))

        # Add difference trace
        fig.add_trace(go.Scatter(
            x=diff['sitetime'], 
            y=diff['Net Production (kWh)'], 
            mode='lines',
            name='Difference (kWh)',
            line=dict(color=color_scheme['difference'])
        ))

        # Update layout
        fig.update_layout(
            title=title,
            xaxis=dict(title='Time'),
            yaxis=dict(title='Energy (kWh)'),
            legend=dict(title="Metrics"),
            template="plotly_white"
        )

        # Convert Plotly figure to HTML
        return pio.to_html(fig, full_html=False)

    except Exception as e:
        # print(f"Error generating combined graph: {e}")
        return f"Error generating graph: {e}"

if __name__ == "__main__":
    app.run(debug=True)