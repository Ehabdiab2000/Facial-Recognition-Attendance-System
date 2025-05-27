import requests
from bs4 import BeautifulSoup
import pandas as pd
import re

class SIRAScraper:
    def __init__(self, base_url):
        self.base_url = base_url
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.companies_data = []

    def scrape_page(self, page_num):
        """Scrape a single page of company listings."""
        url = f"{self.base_url}#page={page_num}"
        try:
            response = self.session.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            # print(f"Page {page_num} content length: {len(response.text)}") # Debug line
            soup = BeautifulSoup(response.text, 'html.parser')
            
            company_cards = soup.select('div.col-md-12.item.data-item') 
            print(f"Found {len(company_cards)} company cards on page {page_num}.")

            if not company_cards and page_num == 1: 
                print(f"No company cards found on page {page_num}. Page HTML (first 2000 chars):")
                print(response.text[:2000])
            
            for card in company_cards:
                company = {
                    'name': self._extract_name(card),
                    'phone': self._extract_phone(card),
                    'email': self._extract_email(card)
                }
                if company['name'] != "N/A" and company['name']:
                    self.companies_data.append(company)
                
            return True
        except requests.exceptions.RequestException as e:
            print(f"Request error scraping page {page_num}: {e}")
            return False
        except Exception as e:
            print(f"Error processing page {page_num}: {e}")
            # if 'card' in locals():
            #     print(f"Problematic card HTML: {card.prettify()[:500]}")
            return False

    def _extract_name(self, card):
        """Extract company name from card."""
        name_element = card.select_one('div.col-md-9 h5') 
        return name_element.text.strip() if name_element else "N/A"

    def _extract_phone(self, card):
        """Extract phone number from card."""
        phone_container = card.select_one('div.col-md-9')
        if phone_container:
            # Attempt 1: Look for <i> tags with phone icons within <p> tags
            phone_icon_elements = phone_container.select('i.fa-phone, i.fa-mobile, i.fa-tty')
            for icon_el in phone_icon_elements:
                if icon_el.parent:
                    phone_text_candidate = icon_el.parent.get_text(separator=' ').strip()
                    phone_match = re.search(r'(?:Phone:|Tel:|Telephone:)?\s*(\+?\d[\d\s()-]{7,}\d)', phone_text_candidate, re.IGNORECASE)
                    if phone_match and phone_match.group(1):
                        cleaned_phone = re.sub(r'[^\d+]', '', phone_match.group(1))
                        if len(cleaned_phone) >= 7:
                            return cleaned_phone
            
            # Attempt 2: Look for <p> tags with text like "Phone:" or "Tel:"
            p_text_elements = phone_container.find_all('p', string=re.compile(r'Phone:|Tel:|Telephone:', re.IGNORECASE))
            for p_el in p_text_elements:
                phone_text_candidate = p_el.get_text(separator=' ').strip()
                phone_match = re.search(r'(?:Phone:|Tel:|Telephone:)?\s*(\+?\d[\d\s()-]{7,}\d)', phone_text_candidate, re.IGNORECASE)
                if phone_match and phone_match.group(1):
                    cleaned_phone = re.sub(r'[^\d+]', '', phone_match.group(1))
                    if len(cleaned_phone) >= 7:
                        return cleaned_phone

            # Attempt 3: Broader search in all text within the specific container for phone patterns
            all_text_in_container = phone_container.get_text(separator=' ')
            phone_match = re.search(r'(\+?\d[\d\s()-]{7,}\d)', all_text_in_container)
            if phone_match and phone_match.group(1):
                cleaned_phone = re.sub(r'[^\d+]', '', phone_match.group(1))
                if len(cleaned_phone) >= 7:
                    return cleaned_phone
        return "N/A"

    def _extract_email(self, card):
        """Extract email from card."""
        email_container = card.select_one('div.col-md-9')
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        if email_container:
            # Attempt 1: Find <a> tag with mailto: href
            email_link = email_container.select_one('a[href^="mailto:"]')
            if email_link and email_link.has_attr('href'):
                email_address = email_link['href'].replace('mailto:', '').split('?')[0].strip()
                if re.fullmatch(email_pattern, email_address):
                    return email_address
            
            # Attempt 2: Find <a> tag containing <i class="fa fa-envelope">
            email_icon_element = email_container.select_one('i.fa-envelope')
            if email_icon_element and email_icon_element.parent and email_icon_element.parent.name == 'a':
                parent_link = email_icon_element.parent
                if parent_link.has_attr('href'):
                    href_val = parent_link['href']
                    if href_val.startswith('mailto:'):
                        email_address = href_val.replace('mailto:', '').split('?')[0].strip()
                        if re.fullmatch(email_pattern, email_address):
                            return email_address
                # Sometimes email is text next to icon in the link
                email_text_in_link = parent_link.get_text(separator=' ').strip()
                email_match_in_link = re.search(email_pattern, email_text_in_link)
                if email_match_in_link:
                    return email_match_in_link.group(0)

            # Attempt 3: Find <p> tags containing "Email:" and then an <a> tag or email text
            p_tags_email = email_container.find_all('p', string=re.compile(r'Email:', re.IGNORECASE))
            for p_tag in p_tags_email:
                link_in_p = p_tag.find('a')
                if link_in_p and link_in_p.has_attr('href') and link_in_p['href'].startswith('mailto:'):
                    email_address = link_in_p['href'].replace('mailto:', '').split('?')[0].strip()
                    if re.fullmatch(email_pattern, email_address):
                        return email_address
                email_match_in_p = re.search(email_pattern, p_tag.get_text(separator=' '))
                if email_match_in_p:
                    return email_match_in_p.group(0)

        # Fallback: Search for email pattern in the whole card text
        card_text = card.get_text(separator=' ')
        email_match = re.search(email_pattern, card_text)
        return email_match.group(0).strip() if email_match else "N/A"

    def scrape_all_pages(self, max_pages=10):
        """Scrape multiple pages with pagination."""
        for page_num in range(1, max_pages + 1):
            print(f"Scraping page {page_num}...")
            if not self.scrape_page(page_num):
                print(f"Note: Issue encountered on page {page_num}. Continuing to next page if possible or stopping.")
                # Decide if to break or continue based on requirements, for now, let's break on major error.
                # break 
        
        return self.companies_data

    def save_to_csv(self, filename='sira_companies.csv'):
        """Save scraped data to CSV file."""
        if not self.companies_data:
            print("No data to save to CSV.")
            return
        try:
            df = pd.DataFrame(self.companies_data)
            df.to_csv(filename, index=False, encoding='utf-8')
            print(f"Data saved to {filename}")
        except Exception as e:
            print(f"Error saving data to CSV {filename}: {e}")


if __name__ == "__main__":
    scraper = SIRAScraper("https://www.sira.gov.ae/en/companies.aspx")
    # Reduced max_pages for testing, increase for full scrape
    companies = scraper.scrape_all_pages(max_pages=3) 
    scraper.save_to_csv()
    if companies:
        print(f"Successfully scraped {len(companies)} companies.")
    else:
        print("No companies were scraped or an error occurred.")