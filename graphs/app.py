from flask import Flask, render_template, request
import pandas as pd
import plotly.express as px
import plotly.io as pio

app = Flask(__name__)

# Route to upload the CSV files
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        try:
            # Get the uploaded files
            file_gunnedah_production = request.files.get("file_gunnedah_production")  # Gunnedah production file
            file_suntop_production = request.files.get("file_suntop_production")      # Suntop production file
            file_gunnedah_revenue1 = request.files.get("file_gunnedah_revenue1")      # Gunnedah revenue meter file 1
            file_gunnedah_revenue2 = request.files.get("file_gunnedah_revenue2")      # Gunnedah revenue meter file 2
            file_suntop_revenue1 = request.files.get("file_suntop_revenue1")          # Suntop revenue meter file 1
            file_suntop_revenue2 = request.files.get("file_suntop_revenue2")          # Suntop revenue meter file 2

            # Initialize graph HTML placeholders
            graph_html_gunnedah_production = None
            graph_html_suntop_production = None
            graph_html_gunnedah_revenue1 = None
            graph_html_gunnedah_revenue2 = None
            graph_html_suntop_revenue1 = None
            graph_html_suntop_revenue2 = None

            if file_gunnedah_production:
                # Generate graph for Gunnedah production
                graph_html_gunnedah_production = process_production_file(file_gunnedah_production, "Gunnedah Total Energy Production Over Time")

            if file_suntop_production:
                # Generate graph for Suntop production
                graph_html_suntop_production = process_production_file(file_suntop_production, "Suntop Total Energy Production Over Time")

            if file_gunnedah_revenue1:
                # Generate graph for Gunnedah revenue meter 1
                graph_html_gunnedah_revenue1 = process_revenue_file(file_gunnedah_revenue1, "Gunnedah Revenue Meter 1 Data")

            if file_gunnedah_revenue2:
                # Generate graph for Gunnedah revenue meter 2
                graph_html_gunnedah_revenue2 = process_revenue_file(file_gunnedah_revenue2, "Gunnedah Revenue Meter 2 Data")

            if file_suntop_revenue1:
                # Generate graph for Suntop revenue meter 1
                graph_html_suntop_revenue1 = process_revenue_file(file_suntop_revenue1, "Suntop Revenue Meter 1 Data")

            if file_suntop_revenue2:
                # Generate graph for Suntop revenue meter 2
                graph_html_suntop_revenue2 = process_revenue_file(file_suntop_revenue2, "Suntop Revenue Meter 2 Data")

            # If no files were uploaded
            if not any([file_gunnedah_production, file_suntop_production, file_gunnedah_revenue1, file_gunnedah_revenue2, file_suntop_revenue1, file_suntop_revenue2]):
                return "Error: Please upload at least one CSV file."

            return render_template(
                "graph.html",
                graph_html_gunnedah_production=graph_html_gunnedah_production or "No Gunnedah production data provided.",
                graph_html_suntop_production=graph_html_suntop_production or "No Suntop production data provided.",
                graph_html_gunnedah_revenue1=graph_html_gunnedah_revenue1 or "No data provided for Gunnedah revenue meter 1.",
                graph_html_gunnedah_revenue2=graph_html_gunnedah_revenue2 or "No data provided for Gunnedah revenue meter 2.",
                graph_html_suntop_revenue1=graph_html_suntop_revenue1 or "No data provided for Suntop revenue meter 1.",
                graph_html_suntop_revenue2=graph_html_suntop_revenue2 or "No data provided for Suntop revenue meter 2."
            )

        except pd.errors.EmptyDataError:
            return "Error: One or more uploaded files are empty or unreadable. Please upload valid CSV files."

        except Exception as e:
            return f"Unexpected error: {str(e)}"

    return render_template("index.html")


# Function to process and generate graph for production files
def process_production_file(file, title):
    try:
        # Read CSV file into a pandas DataFrame
        df = pd.read_csv(file)

        # Check if the DataFrame is empty
        if df.empty:
            return "Error: The uploaded file is empty. Please upload a valid CSV file."

        # Identify energy production columns dynamically
        energy_columns = [col for col in df.columns if "dci" in col and "/5min" in col]
        required_columns = ['sitetime'] + energy_columns

        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return f"Error: The following required columns are missing: {', '.join(missing_columns)}"

        # Drop rows with missing values in critical columns
        df = df.dropna(subset=required_columns)

        # Calculate total production dynamically
        df['total_production'] = df[energy_columns].sum(axis=1)

        # Generate the graph
        return generate_graph(df, title)

    except Exception as e:
        return f"Error processing file: {str(e)}"


# Function to process and generate graph for revenue meter files
def process_revenue_file(file, title):
    try:
        # Read CSV file into a pandas DataFrame, skipping metadata rows
        df = pd.read_csv(file, skiprows=5)

        # Ensure DataFrame has the required columns
        required_columns = ["Date Time", "Export kWh"]
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            return f"Error: Missing columns in uploaded file. Missing: {', '.join(missing_columns)}."

        # Rename columns to standard names for consistency in processing
        df.rename(columns={"Date Time": "Time", "Export kWh": "Exported Energy (kWh)"}, inplace=True)

        # Generate the graph
        return generate_revenue_graph(df, title)

    except Exception as e:
        return f"Error processing file: {str(e)}"


# Function to generate a graph for production data
def generate_graph(df, title):
    try:
        # Create a line plot for total production with the unit in the y-axis label
        fig = px.line(
            df,
            x="sitetime",
            y="total_production",
            title=title,
            labels={"total_production": "Total Production (W)", "sitetime": "Time"}
        )

        # Update hover data
        fig.update_traces(
            hovertemplate="Time=%{x}<br>Total Production (W)=%{y:.2f}"
        )

        # Convert Plotly figure to HTML
        return pio.to_html(fig, full_html=False)

    except Exception as e:
        return f"Error generating graph: {str(e)}"


# Function to generate a graph for revenue meter data
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
        return pio.to_html(fig, full_html=False)

    except Exception as e:
        return f"Error generating graph: {str(e)}"


if __name__ == "__main__":
    app.run(debug=True)
