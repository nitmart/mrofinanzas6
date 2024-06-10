import streamlit as st
import pandas as pd
import nest_asyncio
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
import seaborn as sns
import io
import os

# Set event loop policy to ProactorEventLoop on Windows
if os.name == 'nt':
    asyncio.set_event_loop(asyncio.ProactorEventLoop())

alfa_mio = 'A05709'
clave = 'Luis2020'
empower_url = 'https://mxamro.empowermx.com/emx/billOfWork/selectAircraft.do?service_lookup=search'
crew_url = 'https://mxamro.empowermx.com/emx/billOfWorkAnalysis/aircraftStatusDashboard.do?service_lookup=initialize&/basePerformanceReportSearchRoot/searchCriteriaBasePerformanceReport/preferredCriteria=true'

# Selectors
usuario_selector = '#username'
password_selector = '#password'
login_selector = '#kc-login'

def asignar_aerolinea(tailnumber):
    if tailnumber.startswith('LV'):
        return 'Flybondi'
    elif tailnumber.endswith('LA'):
        return 'LATAM'
    elif tailnumber.startswith('XA'):
        return 'Volaris'
    elif tailnumber.endswith('VL'):
        return 'Volaris'
    elif tailnumber.endswith('A'):
        return 'ATLAS'
    elif tailnumber.endswith('GT'):
        return 'ATLAS'
    elif tailnumber.endswith('FE'):
        return 'FEDEX'
    elif tailnumber.endswith('JB'):
        return 'JetBlue'
    elif tailnumber.startswith('CC'):
        return 'LATAM'
    elif tailnumber.endswith('CM'):
        return 'Amerijet'
    else:
        return 'Desconocido'

# Apply asyncio compatibility
nest_asyncio.apply()

async def login_to_empower(page):
    await page.goto(empower_url)
    await asyncio.sleep(15)
    await page.wait_for_selector(usuario_selector)
    await page.fill(usuario_selector, alfa_mio)
    await page.fill(password_selector, clave)
    await page.click(login_selector)
    await asyncio.sleep(15)

async def fetch_data(page, element_id):
    await page.wait_for_selector(f'#cmi{element_id}')
    await page.click(f'#cmi{element_id}')
    await asyncio.sleep(15)
    await page.wait_for_selector(f'#cmi{element_id}\\.Select\\ WP')
    await page.click(f'#cmi{element_id}\\.Select\\ WP')
    await page.goto(crew_url)
    await asyncio.sleep(15)
    await page.wait_for_selector('div.past24BarChart-table-container')
    element = await page.query_selector('div.past24BarChart-table-container')
    if element:
        content = await element.inner_html()
        soup = BeautifulSoup(content, 'html.parser')
        table = soup.find('table', {'id': 'tablePast24BarChart'})
        headers = [header.get_text(strip=True) for header in table.find_all('th')]
        rows = [[cell.get_text(strip=True) for cell in row.find_all('td')] for row in table.find_all('tr')[1:]]
        df_table = pd.DataFrame(rows, columns=headers)
        df_table['clean_id'] = element_id
        return df_table
    return pd.DataFrame()

async def extract_data(page, element_id):
    element = await page.query_selector(f'div[id="{element_id}"]')
    if element:
        content = await element.inner_html()
        soup = BeautifulSoup(content, 'html.parser')

        def safe_get_text(element):
            return element.get_text(strip=True) if element else 'N/A'

        tailnumber = safe_get_text(soup.find('div', class_='tailnumber'))
        aircraft_type = safe_get_text(soup.find_all('div')[3] if len(soup.find_all('div')) > 3 else None)
        hp = safe_get_text(soup.find_all('div')[4] if len(soup.find_all('div')) > 4 else None)
        check_type = safe_get_text(soup.find('div', class_='checkTypeDisplay'))
        bow_display = safe_get_text(soup.find('div', class_='bowDisplay'))
        matrix_pies = soup.find_all('div', class_='inner-pchart')
        progress_data = {safe_get_text(pie.find('label', class_='matrix-header-label')): {
                'percentage': safe_get_text(pie.find('span', class_='circles-number')),
                'fraction': safe_get_text(pie.find('div', class_='frac'))
            } for pie in matrix_pies}

        data = {
            'Tailnumber': tailnumber,
            'Aircraft Type': aircraft_type,
            'HP': hp,
            'Check Type': check_type,
            'BOW Display': bow_display,
            'Days Percentage': progress_data.get('Days', {}).get('percentage', 'N/A'),
            'Days Fraction': progress_data.get('Days', {}).get('fraction', 'N/A'),
            'Cards Percentage': progress_data.get('Cards', {}).get('percentage', 'N/A'),
            'Cards Fraction': progress_data.get('Cards', {}).get('fraction', 'N/A'),
            'Labor Percentage': progress_data.get('Labor', {}).get('percentage', 'N/A'),
            'Labor Fraction': progress_data.get('Labor', {}).get('fraction', 'N/A')
        }
        return data
    return None

async def buscar_id(browser):
    page = await browser.new_page()
    await login_to_empower(page)
    await asyncio.sleep(5)
    ids = await page.evaluate('''() => {
        return Array.from(document.querySelectorAll('[id]')).map(element => element.id).filter(id => id.startsWith('cmi'));
    }''')
    all_data = []
    for element_id in ids[:12]:
        clean_id = element_id[3:]
        data = await extract_data(page, clean_id)
        if data:
            record = {'clean_id': clean_id, **data}
            all_data.append(record)
    await page.close()
    return pd.DataFrame(all_data)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        df1 = await buscar_id(browser)
        all = []
        for element_id in df1['clean_id']:
            page = await browser.new_page()
            await login_to_empower(page)

            data2 = await fetch_data(page, element_id)
            all.append(data2)
            await page.close()
        df2 = pd.concat(all, ignore_index=True)

        df2.columns = ['Category', 'Routine', 'Last 24 Hrs', 'N/R', 'Last 24 Hrs (N/R)', 'Total', 'clean_id']
        df2_filtered = df2[df2['Category'] == 'Production: Total and Last 24 Hrs']
        tabla1 = pd.merge(df1, df2_filtered, on='clean_id', how='left')

        def split_fraction(df, column_name):
            df[[f'{column_name} Num', f'{column_name} Denom']] = df[column_name].str.split('/', expand=True)
            return df

        fraction_columns = ['Days Fraction', 'Cards Fraction', 'Labor Fraction']
        for col in fraction_columns:
            tabla1 = split_fraction(tabla1, col)

        numeric_cols = ['Days Fraction Num', 'Days Fraction Denom', 'Cards Fraction Num', 'Cards Fraction Denom', 'Labor Fraction Num', 'Labor Fraction Denom', 'Routine']
        for col in numeric_cols:
            tabla1[col] = pd.to_numeric(tabla1[col], errors='coerce')

        tabla1['Real'] = (tabla1['Labor Fraction Num'] + tabla1['Routine']) * 42.75
        tabla1['Ideal'] = (tabla1['Labor Fraction Denom'] / tabla1['Days Fraction Denom']) * tabla1['Days Fraction Num'] * 50
        tabla1['Dolares'] = tabla1['Ideal'] - tabla1['Real']
        tabla1['Dolares'] = tabla1['Dolares'].astype(int)
        tabla1['Status'] = tabla1['Dolares'].apply(lambda x: 'GANANDO' if x > 0 else 'PERDIENDO')
        tabla1.rename(columns={'Routine': 'Non Production'}, inplace=True)
        await browser.close()

        return tabla1

def color_status(val):
    color = 'green' if val == 'GANANDO' else 'red'
    return f'background-color: {color}'

st.title("Mexicana MRO Financial Metrics")

if st.button("Run Data Extraction"):
    st.write("Running data extraction, please wait...")
    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)
    tabla1 = loop.run_until_complete(main())

    tabla1 = tabla1[tabla1['Tailnumber'] != 'TM AEROLINEAS SHOP']
    tabla1.loc[:, 'Airline'] = tabla1['Tailnumber'].apply(asignar_aerolinea)

    final_table = tabla1[['Airline','Tailnumber', 'Days Fraction', 'Cards Fraction', 'Labor Fraction', 'Non Production', 'Dolares', 'Status']]

    st.write(" General Status  ")
    styled_table = final_table.style.applymap(color_status, subset=['Status'])
    st.dataframe(styled_table)

   
