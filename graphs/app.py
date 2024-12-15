from flask import Flask, render_template, request
import pandas as pd
import plotly.express as px
import plotly.io as pio

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/gunnedah", methods=["POST"])
def gunnedah():
    if request.method == "POST":
        try:
            # Retrieve uploaded files
            production_file = request.files.get("file_gunnedah_production")
            revenue_file1 = request.files.get("file_gunnedah_revenue1")
            revenue_file2 = request.files.get("file_gunnedah_revenue2")

            if not (production_file and revenue_file1 and revenue_file2):
                return "Error: Please upload all required files (production, revenue1, revenue2)."

            # Process production and revenue data
            jan_data, may_data = process_production_file(production_file)
            revenue_jan = process_revenue_file(revenue_file1)
            revenue_may = process_revenue_file(revenue_file2)

            # Calculate difference
            jan_diff, may_diff = difference(production_file, revenue_jan, revenue_may)


            # Generate graphs
            graphs = {
                "production": generate_graph(jan_data, may_data, "Gunnedah Production"),
                "revenue1": generate_revenue_graph(revenue_jan, "Gunnedah Revenue Meter (January)"),
                "revenue2": generate_revenue_graph(revenue_may, "Gunnedah Revenue Meter (May)"),
                "difference": generate_difference_graph(jan_diff, may_diff, "Gunnedah Production vs Revenue Difference"),
            }

            return render_template("graph_gunnedah.html", graphs=graphs)

        except Exception as e:
            return f"Error occurred: {str(e)}"


# Processing Functions
def process_production_file(file):
    df = pd.read_csv(file)
    if df.empty:
        raise ValueError("Production file is empty.")

    # Identify energy columns dynamically
    energy_columns = [col for col in df.columns if "dci" in col and "/5min" in col]
    if not energy_columns:
        raise ValueError("No valid energy production columns found.")
    

    # Calculate total production
    df["total_production"] = df[energy_columns].sum(axis=1)
    df["sitetime"] = pd.to_datetime(df["sitetime"], errors="coerce")
    df.dropna(subset=["sitetime"], inplace=True)

    # Filter data for January and May
    jan_data = df[df["sitetime"].dt.month == 1]
    may_data = df[df["sitetime"].dt.month == 5]

    return jan_data, may_data

def process_revenue_file(file):

    df = pd.read_csv(file, skiprows=5)

    # Ensure DataFrame has the required columns
    required_columns = ["Date Time", "Export kWh"]
    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        return f"Error: Missing columns in uploaded file. Missing: {', '.join(missing_columns)}."

    # Rename columns to standard names for consistency in processing
    df.rename(columns={"Date Time": "Time", "Export kWh": "Exported Energy (kWh)"}, inplace=True)

    # Generate the graph
    return df


# Calculate the difference between production and revenue
def difference(production_file, revenue_file1, revenue_file2):
    try:
        # Process production data
        jan_data, may_data = process_production_file(production_file)
        print("January Production Data (Head):")
        print(jan_data.head())  # Debug print for January production data
        print("May Production Data (Head):")
        print(may_data.head())  # Debug print for May production data
        
        # Process revenue data
        revenue_jan = process_revenue_file(revenue_file1)
        revenue_may = process_revenue_file(revenue_file2)
        print("January Revenue Data (Head):")
        print(revenue_jan.head())  # Debug print for January revenue data
        print("May Revenue Data (Head):")
        print(revenue_may.head())  # Debug print for May revenue data
    
        # Ensure necessary columns exist
        required_columns = ['total_production', 'sitetime']
        for data, name in zip([jan_data, may_data], ['January', 'May']):
            for col in required_columns:
                if col not in data.columns:
                    raise KeyError(f"Column '{col}' missing in {name} production data.")
        
        revenue_columns = ['Exported Energy (kWh)']
        # for data, name in zip([revenue_jan, revenue_may], ['January', 'May']):
        #     for col in revenue_columns:
        #         if col not in data.columns:
        #             raise KeyError(f"Column '{col}' missing in {name} revenue data.")
        
        # Convert production timestamps to datetime
        jan_data['sitetime'] = pd.to_datetime(jan_data['sitetime'])
        may_data['sitetime'] = pd.to_datetime(may_data['sitetime'])
        revenue_jan['Time'] = pd.to_datetime(revenue_jan['Time'])
        revenue_may['Time'] = pd.to_datetime(revenue_may['Time'])
        
        # Convert production data to kWh
        system_voltage = 1500  # volts
        time_interval_hours = 5 / 60  # 5-minute intervals
        jan_data['converted_production'] = (jan_data['total_production'] * system_voltage * time_interval_hours) / 1000
        may_data['converted_production'] = (may_data['total_production'] * system_voltage * time_interval_hours) / 1000

        # Merge production and revenue data on timestamps
        merged_jan = pd.merge(
            jan_data[['sitetime', 'converted_production']],
            revenue_jan[['Time', 'Exported Energy (kWh)']],
            left_on='sitetime',
            right_on='Time',
            how='inner'
        )
        merged_may = pd.merge(
            may_data[['sitetime', 'converted_production']],
            revenue_may[['Time', 'Exported Energy (kWh)']],
            left_on='sitetime',
            right_on='Time',
            how='inner'
        )

        # Calculate net production
        merged_jan['Net Production (kWh)'] = merged_jan['converted_production'] - merged_jan['Exported Energy (kWh)']
        merged_may['Net Production (kWh)'] = merged_may['converted_production'] - merged_may['Exported Energy (kWh)']

        # Extract final results
        jan_total_data_full = merged_jan[['sitetime', 'Net Production (kWh)']]
        may_total_data_full = merged_may[['sitetime', 'Net Production (kWh)']]

        # Print final data shapes
        print("January Data Shape (Final):", jan_total_data_full.shape)
        print("May Data Shape (Final):", may_total_data_full.shape)
        # Print shapes for verification
        print("January Data Converted Shape:", jan_data.shape)
        print("July Data Converted Shape:", may_data.shape)
        print("Revenue January Shape:", revenue_jan.shape)
        print("Revenue July Shape:", revenue_may.shape)
        print("Final January Data Shape:", jan_total_data_full.shape)
        print("Final July Data Shape:", may_total_data_full.shape)
        
        return jan_total_data_full, may_total_data_full

    except Exception as e:
        print(f"Error occurred: {e}")
        return None, None



# Graph Generation Functions
def generate_graph(df_jan, df_may, title):
    fig_jan = px.line(
        df_jan, x="sitetime", y="total_production",
        title=f"{title} - January", labels={"sitetime": "Time", "total_production": "Total Production (W)"}
    )
    fig_may = px.line(
        df_may, x="sitetime", y="total_production",
        title=f"{title} - May", labels={"sitetime": "Time", "total_production": "Total Production (W)"}
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

        print("January Difference Data (Head):")
        print(jan_diff.head())  # Debug print for January difference data
        
        # Generate graph for January difference
        fig_jan = px.line(
            jan_diff,
            x="sitetime",
            y="Net Production (kWh)",
            title=f"{title} - January",
            labels={"sitetime": "Date", "Net Production (kWh)": "Net Difference (kWh)"}
        )

        # Generate graph for May difference
        fig_may = px.line(
            may_diff,
            x="sitetime",
            y="Net Production (kWh)",
            title=f"{title} - May",
            labels={"sitetime": "Date", "Net Production (kWh)": "Net Difference (kWh)"}
        )

        return {
            "january": pio.to_html(fig_jan, full_html=False),
            "may": pio.to_html(fig_may, full_html=False),
        }
    except Exception as e:
        print(f"Error generating difference graph: {e}")
        return {
            "january": f"Error generating January graph: {e}",
            "may": f"Error generating May graph: {e}",
        }

@app.route("/suntop", methods=["POST"])
def suntop():
    if request.method == "POST":
        try:
            # Retrieve uploaded files
            production_file = request.files.get("file_suntop_production")
            revenue_file1 = request.files.get("file_suntop_revenue1")
            revenue_file2 = request.files.get("file_suntop_revenue2")

            if not (production_file and revenue_file1 and revenue_file2):
                return "Error: Please upload all required files (production, revenue1, revenue2)."

            # Process production and revenue data
            jan_data, may_data = process_production_file(production_file)
            revenue_jan = process_revenue_file(revenue_file1)
            revenue_may = process_revenue_file(revenue_file2)

            # Calculate difference
            jan_diff, may_diff = difference(production_file, revenue_jan, revenue_may)


            # Generate graphs
            graphs = {
                "production": generate_graph(jan_data, may_data, "Suntop Production"),
                "revenue1": generate_revenue_graph(revenue_jan, "Suntop Revenue Meter (January)"),
                "revenue2": generate_revenue_graph(revenue_may, "Suntop Revenue Meter (May)"),
                "difference": generate_difference_graph(jan_diff, may_diff, "Suntop Production vs Revenue Difference"),
            }

            return render_template("graph_suntop.html", graphs=graphs)

        except Exception as e:
            return f"Error occurred: {str(e)}"
        
# Processing Functions
def process_production_file(file):
    df = pd.read_csv(file)
    if df.empty:
        raise ValueError("Production file is empty.")

    # Identify energy columns dynamically
    energy_columns = [col for col in df.columns if "dci" in col and "/5min" in col]
    if not energy_columns:
        raise ValueError("No valid energy production columns found.")
    

    # Calculate total production
    df["total_production"] = df[energy_columns].sum(axis=1)
    df["sitetime"] = pd.to_datetime(df["sitetime"], errors="coerce")
    df.dropna(subset=["sitetime"], inplace=True)

    # Filter data for January and May
    jan_data = df[df["sitetime"].dt.month == 1]
    may_data = df[df["sitetime"].dt.month == 5]

    return jan_data, may_data

def process_revenue_file(file):

    df = pd.read_csv(file, skiprows=5)

    # Ensure DataFrame has the required columns
    required_columns = ["Date Time", "Export kWh"]
    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        return f"Error: Missing columns in uploaded file. Missing: {', '.join(missing_columns)}."

    # Rename columns to standard names for consistency in processing
    df.rename(columns={"Date Time": "Time", "Export kWh": "Exported Energy (kWh)"}, inplace=True)

    # Generate the graph
    return df


# Calculate the difference between production and revenue
def difference(production_file, revenue_file1, revenue_file2):
    try:
        # Process production data
        jan_data, may_data = process_production_file(production_file)
        print("January Production Data (Head):")
        print(jan_data.head())  # Debug print for January production data
        print("May Production Data (Head):")
        print(may_data.head())  # Debug print for May production data
        
        # Process revenue data
        revenue_jan = process_revenue_file(revenue_file1)
        revenue_may = process_revenue_file(revenue_file2)
        print("January Revenue Data (Head):")
        print(revenue_jan.head())  # Debug print for January revenue data
        print("May Revenue Data (Head):")
        print(revenue_may.head())  # Debug print for May revenue data
    
        # Ensure necessary columns exist
        required_columns = ['total_production', 'sitetime']
        for data, name in zip([jan_data, may_data], ['January', 'May']):
            for col in required_columns:
                if col not in data.columns:
                    raise KeyError(f"Column '{col}' missing in {name} production data.")
        
        revenue_columns = ['Exported Energy (kWh)']
        # for data, name in zip([revenue_jan, revenue_may], ['January', 'May']):
        #     for col in revenue_columns:
        #         if col not in data.columns:
        #             raise KeyError(f"Column '{col}' missing in {name} revenue data.")
        
        # Convert production timestamps to datetime
        jan_data['sitetime'] = pd.to_datetime(jan_data['sitetime'])
        may_data['sitetime'] = pd.to_datetime(may_data['sitetime'])
        revenue_jan['Time'] = pd.to_datetime(revenue_jan['Time'])
        revenue_may['Time'] = pd.to_datetime(revenue_may['Time'])
        
        # Convert production data to kWh
        system_voltage = 1500  # volts
        time_interval_hours = 5 / 60  # 5-minute intervals
        jan_data['converted_production'] = (jan_data['total_production'] * system_voltage * time_interval_hours) / 1000
        may_data['converted_production'] = (may_data['total_production'] * system_voltage * time_interval_hours) / 1000

        # Merge production and revenue data on timestamps
        merged_jan = pd.merge(
            jan_data[['sitetime', 'converted_production']],
            revenue_jan[['Time', 'Exported Energy (kWh)']],
            left_on='sitetime',
            right_on='Time',
            how='inner'
        )
        merged_may = pd.merge(
            may_data[['sitetime', 'converted_production']],
            revenue_may[['Time', 'Exported Energy (kWh)']],
            left_on='sitetime',
            right_on='Time',
            how='inner'
        )

        # Calculate net production
        merged_jan['Net Production (kWh)'] = merged_jan['converted_production'] - merged_jan['Exported Energy (kWh)']
        merged_may['Net Production (kWh)'] = merged_may['converted_production'] - merged_may['Exported Energy (kWh)']

        # Extract final results
        jan_total_data_full = merged_jan[['sitetime', 'Net Production (kWh)']]
        may_total_data_full = merged_may[['sitetime', 'Net Production (kWh)']]

        # Print final data shapes
        print("January Data Shape (Final):", jan_total_data_full.shape)
        print("May Data Shape (Final):", may_total_data_full.shape)
        # Print shapes for verification
        print("January Data Converted Shape:", jan_data.shape)
        print("July Data Converted Shape:", may_data.shape)
        print("Revenue January Shape:", revenue_jan.shape)
        print("Revenue July Shape:", revenue_may.shape)
        print("Final January Data Shape:", jan_total_data_full.shape)
        print("Final July Data Shape:", may_total_data_full.shape)
        
        return jan_total_data_full, may_total_data_full

    except Exception as e:
        print(f"Error occurred: {e}")
        return None, None



# Graph Generation Functions
def generate_graph(df_jan, df_may, title):
    fig_jan = px.line(
        df_jan, x="sitetime", y="total_production",
        title=f"{title} - January", labels={"sitetime": "Time", "total_production": "Total Production (W)"}
    )
    fig_may = px.line(
        df_may, x="sitetime", y="total_production",
        title=f"{title} - May", labels={"sitetime": "Time", "total_production": "Total Production (W)"}
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

        print("January Difference Data (Head):")
        print(jan_diff.head())  # Debug print for January difference data
        
        # Generate graph for January difference
        fig_jan = px.line(
            jan_diff,
            x="sitetime",
            y="Net Production (kWh)",
            title=f"{title} - January",
            labels={"sitetime": "Date", "Net Production (kWh)": "Net Difference (kWh)"}
        )

        # Generate graph for May difference
        fig_may = px.line(
            may_diff,
            x="sitetime",
            y="Net Production (kWh)",
            title=f"{title} - May",
            labels={"sitetime": "Date", "Net Production (kWh)": "Net Difference (kWh)"}
        )

        return {
            "january": pio.to_html(fig_jan, full_html=False),
            "may": pio.to_html(fig_may, full_html=False),
        }
    except Exception as e:
        print(f"Error generating difference graph: {e}")
        return {
            "january": f"Error generating January graph: {e}",
            "may": f"Error generating May graph: {e}",
        }


if __name__ == "__main__":
    app.run(debug=True)