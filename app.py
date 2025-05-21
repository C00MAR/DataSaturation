import time
import json
import threading
from collections import deque
from flask import Flask, render_template, Response
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

app = Flask(__name__)

# Global variable to store a history of scraped data
scraped_data_queue = deque(maxlen=5) # Store last 5 scraped data points
scraping_active = True
interpolation_interval = 0.1 # Desired refresh rate for client (e.g., 100ms)

def scrape_worldometers():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    try:
        print("Navigating to worldometers.info...")
        driver.get("https://www.worldometers.info/")
        
        counters = {
            "current_population": "Current World Population",
            "births_this_year": "Births this year",
            "births_today": "Births today",
            "dth1s_this_year": "Deaths this year",
            "dth1s_today": "Deaths today", 
            "absolute_growth_year": "Net population growth this year",
            "absolute_growth": "Net population growth today"
        }
        
        while scraping_active:
            data = {}
            
            # Extract each counter
            for counter_id, counter_name in counters.items():
                try:
                    # Find elements by rel attribute
                    element = driver.find_element(By.CSS_SELECTOR, f'span.rts-counter[rel="{counter_id}"]')
                    
                    # Extract the text value
                    counter_value_str = element.text.strip() # Get text and remove leading/trailing whitespace
                    
                    # --- ADDED ERROR HANDLING AND CLEANING ---
                    if counter_value_str: # Check if the string is not empty
                        try:
                            # Remove commas and convert to int
                            counter_value = int(counter_value_str.replace(',', ''))
                            data[counter_name] = counter_value
                        except ValueError:
                            # If conversion fails (e.g., "N/A" or "Loading..."), print a warning and skip
                            print(f"Warning: Could not convert '{counter_value_str}' for {counter_name} to int. Skipping this value.")
                            # Optionally, you could store a default value like 0 or None if it makes sense
                            # data[counter_name] = 0 
                    else:
                        print(f"Warning: Extracted empty string for {counter_name}. Skipping this value.")
                        # Optionally, store a default value or None if the element is empty
                        # data[counter_name] = 0

                except Exception as e:
                    print(f"Error extracting {counter_name}: {e}")
            
            if data: # Only append if we successfully extracted some data
                data['scrape_timestamp'] = time.time()
                scraped_data_queue.append(data)
                print(f"Data scraped and added to queue at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data['scrape_timestamp']))}")
            else:
                print("No data extracted in this cycle. Skipping queue update.")
            
            time.sleep(0.5)
            
            # Refresh the page occasionally
            if scraping_active and time.time() % 300 < 1: # Reduced refresh check window
                driver.refresh()
                time.sleep(5) 
                
    except Exception as e:
        print(f"An error occurred in scraping thread: {e}")
    finally:
        driver.quit()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/stream')
def stream():
    def event_stream():
        current_interpolated_data = None
        last_scraped_data_processed_timestamp = 0

        while True:
            if len(scraped_data_queue) >= 2:
                # Get the last two scraped data points
                # Ensure we process new scraped data only once
                if scraped_data_queue[-1]['scrape_timestamp'] > last_scraped_data_processed_timestamp:
                    data_current = scraped_data_queue[-1]
                    data_previous = scraped_data_queue[-2]

                    time_diff_scrape = data_current['scrape_timestamp'] - data_previous['scrape_timestamp']
                    
                    if time_diff_scrape > 0: # Avoid division by zero
                        # Calculate growth rates per second for each counter
                        growth_rates = {}
                        for counter_name in data_current:
                            if isinstance(data_current[counter_name], int) and isinstance(data_previous.get(counter_name), int):
                                growth_rates[counter_name] = (data_current[counter_name] - data_previous[counter_name]) / time_diff_scrape
                            else:
                                growth_rates[counter_name] = 0 # Cannot interpolate non-numeric values
                        
                        # Initialize or update the interpolation base
                        if current_interpolated_data is None or 'base_timestamp' not in current_interpolated_data:
                            current_interpolated_data = {**data_previous, 'base_timestamp': data_previous['scrape_timestamp']}
                        elif data_current['scrape_timestamp'] > current_interpolated_data['base_timestamp']:
                             # If a new 'current' scraped data point is available, set it as the new base
                            current_interpolated_data = {**data_current, 'base_timestamp': data_current['scrape_timestamp']}

                        last_scraped_data_processed_timestamp = data_current['scrape_timestamp']

            # If we have a base, start interpolating
            if current_interpolated_data and 'base_timestamp' in current_interpolated_data:
                time_elapsed_since_base = time.time() - current_interpolated_data['base_timestamp']
                
                interpolated_output = {}
                for counter_name, value in current_interpolated_data.items():
                    if isinstance(value, int) and counter_name in growth_rates:
                        interpolated_output[counter_name] = int(value + (growth_rates[counter_name] * time_elapsed_since_base))
                    elif counter_name not in ['scrape_timestamp', 'base_timestamp']:
                        interpolated_output[counter_name] = value # Pass non-numeric values directly

                interpolated_output['timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S')
                yield f"data: {json.dumps(interpolated_output)}\n\n"
            else:
                # If no data yet, send a placeholder or wait
                yield f"data: {json.dumps({'message': 'Waiting for initial data...'})}\n\n"

            time.sleep(interpolation_interval)

    return Response(event_stream(), mimetype="text/event-stream")

if __name__ == "__main__":
    scraper_thread = threading.Thread(target=scrape_worldometers)
    scraper_thread.daemon = True
    scraper_thread.start()
    
    app.run(debug=True, threaded=True, host='0.0.0.0')