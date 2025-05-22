import os
import time
import json
import threading
from collections import deque
from flask import Flask, render_template, Response
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
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
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    # Configuration des attentes
    wait = WebDriverWait(driver, 20)
    
    try:
        print("Navigating to worldometers.info...")
        driver.get("https://www.worldometers.info/")
        
        # Attendre que la page soit complètement chargée
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "rts-counter")))
        
        # Faire défiler la page pour s'assurer que tous les éléments sont visibles
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(2)
        
        counters = {
            "current_population": "Current World Population",
            "births_this_year": "Births this year", 
            "dth1s_this_year": "Deaths this year",
            "automobile_produced/this_year": "Car Production this year",
            "cellular/today": "Cellular phones sold today",
            "google_searches/today": "Google searches today",
            "co2_emissions/this_year": "CO2 emissions this year (tons)",
            "water_consumed/this_year": "Water used this year (million L)",
            "cigarettes_smoked/today": "Cigarettes smoked today",
        }
        
        while scraping_active:
            data = {}
            
            # Faire défiler périodiquement pour réactiver les compteurs
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            time.sleep(0.5)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
            
            # Extract each counter
            for counter_id, counter_name in counters.items():
                try:
                    # Attendre que l'élément soit présent
                    element = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, f'span.rts-counter[rel="{counter_id}"]'))
                    )
                    
                    # S'assurer que l'élément est visible
                    driver.execute_script("arguments[0].scrollIntoView(true);", element)
                    time.sleep(0.2)
                    
                    # Essayer plusieurs méthodes pour obtenir le texte
                    counter_value_str = ""
                    try:
                        counter_value_str = element.get_attribute('textContent') or element.text
                    except:
                        try:
                            counter_value_str = driver.execute_script("return arguments[0].textContent;", element)
                        except:
                            counter_value_str = element.text
                    
                    counter_value_str = counter_value_str.strip()
                    
                    print(f"Found {counter_name}: '{counter_value_str}'")
                    
                    # --- ADDED ERROR HANDLING AND CLEANING ---
                    if counter_value_str: # Check if the string is not empty
                        try:
                            # Remove commas and convert to int
                            counter_value = int(counter_value_str.replace(',', ''))
                            data[counter_name] = counter_value
                            print(f"Successfully parsed {counter_name}: {counter_value}")
                        except ValueError as ve:
                            # If conversion fails (e.g., "N/A" or "Loading..."), print a warning and skip
                            print(f"Warning: Could not convert '{counter_value_str}' for {counter_name} to int: {ve}")
                            # Optionally, you could store a default value like 0 or None if it makes sense
                            data[counter_name] = 0 
                    else:
                        print(f"Warning: Extracted empty string for {counter_name}. Skipping this value.")
                        # Optionally, store a default value or None if the element is empty
                        data[counter_name] = 0

                except TimeoutException:
                    print(f"Timeout: Could not find element for {counter_name} (rel='{counter_id}')")
                    # Essayer de trouver l'élément avec un sélecteur différent
                    try:
                        alternative_elements = driver.find_elements(By.XPATH, f"//span[@rel='{counter_id}']")
                        if alternative_elements:
                            element = alternative_elements[0]
                            counter_value_str = element.text.strip()
                            if counter_value_str:
                                counter_value = int(counter_value_str.replace(',', ''))
                                data[counter_name] = counter_value
                                print(f"Found {counter_name} with alternative selector: {counter_value}")
                        else:
                            print(f"No alternative element found for {counter_name}")
                    except Exception as alt_e:
                        print(f"Alternative method failed for {counter_name}: {alt_e}")
                
                except NoSuchElementException:
                    print(f"Element not found: {counter_name} (rel='{counter_id}')")
                    
                except Exception as e:
                    print(f"Error extracting {counter_name}: {e}")
            
            if data: # Only append if we successfully extracted some data
                data['scrape_timestamp'] = time.time()
                scraped_data_queue.append(data)
                # print(f"Data scraped and added to queue at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data['scrape_timestamp']))}")
                print(f"Total counters found: {len(data)-1}")  # -1 pour exclure le timestamp
            else:
                print("No data extracted in this cycle. Skipping queue update.")
            
            time.sleep(2)  # Augmenter légèrement le délai
            
            # Refresh the page occasionally
            if scraping_active and time.time() % 300 < 2: # Reduced refresh check window
                print("Refreshing page...")
                driver.refresh()
                # Attendre que la page soit rechargée
                wait.until(EC.presence_of_element_located((By.CLASS_NAME, "rts-counter")))
                time.sleep(5) 
                
    except Exception as e:
        print(f"An error occurred in scraping thread: {e}")
    finally:
        driver.quit()

def debug_page_elements(driver):
    """Fonction pour déboguer et lister tous les compteurs disponibles"""
    try:
        all_counters = driver.find_elements(By.CLASS_NAME, "rts-counter")
        print(f"Found {len(all_counters)} total rts-counter elements:")
        
        for i, counter in enumerate(all_counters):
            rel_attr = counter.get_attribute('rel')
            text_content = counter.text or counter.get_attribute('textContent') or 'N/A'
            print(f"  {i+1}. rel='{rel_attr}' text='{text_content}'")
            
    except Exception as e:
        print(f"Error in debug function: {e}")

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
    
    # port = int(os.environ.get("PORT", 8080))
    # app.run(host='0.0.0.0', port=port)
    app.run(debug=True, threaded=True, host='0.0.0.0')