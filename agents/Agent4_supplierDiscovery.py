import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from utils.groq_helper import groq
from config.settings import GROQ_MODELS
from utils.logger import log_info, log_error
from dotenv import load_dotenv
from tavily import TavilyClient
import requests
from bs4 import BeautifulSoup
import json
import time
import re

load_dotenv()

class SupplierDiscovery(BaseAgent):
    """Find suppliers via web search, scrape websites, and assess quality."""
    
    def __init__(self):
        super().__init__(
            name="Agent 4 - Supplier Discovery",
            role="Supplier Finder & Risk Assessor",
            goal="Find reliable suppliers and assess their risk level",
            backstory="Expert at finding and evaluating suppliers using web research"
        )
        self.tavily = TavilyClient(api_key=os.environ.get('TAVILY_API_KEY'))
    
    def execute(self, item_code: str, item_name: str, location: str = "India", top_n: int = 5, force_web: bool = False):
        """Search suppliers, scrape websites, and assess quality. Checks local DB first unless forced."""
        self.log_start(f"Finding suppliers for {item_name}")
        
        # Step 0: Check Internal Suppliers History first
        if not force_web:
            log_info(f"Checking internal supplier history for {item_name}...", self.name)
            try:
                history_path = 'data/supplier_history.json'
                if os.path.exists(history_path):
                    with open(history_path, 'r') as f:
                        history_data = json.load(f)
                    
                    db_suppliers_map = {}
                    
                    # Since keys were migrated to perfectly match inventory item_names,
                    # we can use the naturally built-in Python dictionary lookup logic.
                    if item_name in history_data:
                        records = history_data[item_name]
                        for row in records:
                            sup_name = row.get('supplier_name', 'Unknown')
                            row['item_name'] = item_name
                            db_suppliers_map[sup_name] = row
                            
                    if db_suppliers_map:
                        db_suppliers = []
                        for sup_name, row in db_suppliers_map.items():
                            db_suppliers.append({
                                'supplier_name': sup_name,
                                'contact_email': row.get('contact_email', ''),
                                'phone': '',
                                'location': location,
                                'rating': row.get('rating', 4.0),
                                'has_iso_certification': row.get('has_iso_certification', False),
                                'years_in_business': row.get('years_in_business', 'Unknown'),
                                'url': '',
                                'website': '',
                                'source_title': sup_name,
                                'is_historical': True,
                                'products_supplied': row.get('item_name', ''),
                                'historical_exception': row.get('exceptions_handled', 'None'),
                                'historical_compensation': row.get('compensation', 'None'),
                                'quantity_bought': row.get('quantity_bought', 0),
                                'unit_price': row.get('unit_price', 0),
                                'total_price': row.get('total_price', 0),
                            })
                        
                        # Score them just like web suppliers
                        scored_db_suppliers = self._calculate_quality_scores(db_suppliers)
                        top_db_suppliers = sorted(scored_db_suppliers, key=lambda x: x['quality_score'], reverse=True)[:top_n]
                        
                        self.log_complete("Supplier discovery", f"Found {len(top_db_suppliers)} approved suppliers in History")
                        
                        return {
                            'item_code': item_code,
                            'item_name': item_name,
                            'search_query': 'internal_history_search',
                            'suppliers': top_db_suppliers,
                            'suppliers_found': len(top_db_suppliers),
                            'total_found': len(top_db_suppliers),
                            'from_db': True
                        }
            except Exception as e:
                log_error(f"Failed to check internal history DB: {e}", self.name)
        
        # Step 1: Search the web
        search_query = f"{item_name} supplier {location}"
        search_results = self._search_web(search_query, max_results=15)
        
        if not search_results:
            self.log_error("Supplier search", "No results found")
            return {
                'item_code': item_code,
                'item_name': item_name,
                'search_query': search_query,
                'suppliers': [],
                'suppliers_found': 0,
                'total_found': 0,
                'error': 'No search results found'
            }
        
        # Step 2: Scrape each supplier website
        suppliers = []
        for result in search_results[:15]:  # Process top 15 results
            supplier_data = self._scrape_supplier(result)
            if supplier_data:
                suppliers.append(supplier_data)
            time.sleep(0.5)  
        
        # Step 3: Calculate quality scores
        scored_suppliers = self._calculate_quality_scores(suppliers)
        
        # Step 4: Sort by quality score (HIGHEST first = BEST suppliers) and return top N
        top_suppliers = sorted(scored_suppliers, key=lambda x: x['quality_score'], reverse=True)[:top_n]
        
        self.log_complete("Supplier discovery", f"Found {len(top_suppliers)} suppliers")
        
        return {
            'item_code': item_code,
            'item_name': item_name,
            'search_query': search_query,
            'suppliers': top_suppliers,
            'suppliers_found': len(suppliers),
            'total_found': len(suppliers)
        }
    
    def _search_web(self, query: str, max_results: int = 15):
        """Search Tavily for suppliers with retry logic and fallback."""
        max_retries = 3

        for attempt in range(max_retries):
            try:
                log_info(f"Searching: {query} (attempt {attempt + 1})", self.name)
                response = self.tavily.search(query=query, max_results=max_results)
                raw_results = response.get('results', [])
                results = [{'title': r.get('title', ''), 'href': r.get('url', '')} for r in raw_results]

                if not results:
                    log_info("Initial search returned 0 results. Retrying with simpler query...", self.name)
                    simpler_query = " ".join(query.split()[:2])
                    response = self.tavily.search(query=simpler_query, max_results=max_results)
                    raw_results = response.get('results', [])
                    results = [{'title': r.get('title', ''), 'href': r.get('url', '')} for r in raw_results]

                if results:
                    log_info(f"Found {len(results)} search results", self.name)
                    return results

            except Exception as e:
                log_error(f"Search attempt {attempt + 1} failed: {e}", self.name)
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue

        log_info("All search attempts failed. Using fallback supplier list.", self.name)
        return [
            {'title': 'Grainger Industrial Supply', 'href': 'https://www.grainger.com'},
            {'title': 'McMaster-Carr', 'href': 'https://www.mcmaster.com'},
            {'title': 'TATA Steel', 'href': 'https://www.tatasteel.com'}
        ]
    
    def _is_valid_supplier_url(self, url: str, title: str) -> bool:
        """Check if URL is likely a real supplier website."""
        url_lower = url.lower()
        title_lower = title.lower()
        
        # Blacklist: Common non-supplier domains
        blacklist_domains = [
            'indiamart.com', 'tradeindia.com', 'justdial.com', 'sulekha.com',
            'exportersindia.com', 'alibaba.com', 'amazon.in', 'flipkart.com',
            'wikipedia.org', 'linkedin.com', 'facebook.com', 'instagram.com',
            'youtube.com', 'twitter.com', 'quora.com', 'reddit.com',
            'blog', 'news', 'article', 'medium.com', 'blogspot.com',
            'wordpress.com', 'wix.com', 'weebly.com', 'jimdo.com'
        ]
        
        # Check if URL contains blacklisted domains
        if any(domain in url_lower for domain in blacklist_domains):
            log_info(f"Filtered out: {url} (marketplace/blog/social)", self.name)
            return False
        
        # Blacklist: Title patterns that indicate non-suppliers
        blacklist_titles = [
            'top 10', 'best suppliers', 'list of', 'directory',
            'how to find', 'guide to', 'blog', 'news', 'article'
        ]
        
        if any(pattern in title_lower for pattern in blacklist_titles):
            log_info(f"Filtered out: {title} (directory/blog)", self.name)
            return False
        
        return True
    
    def _scrape_supplier(self, search_result: dict):
        """Scrape supplier website and extract information."""
        url = search_result.get('href')
        title = search_result.get('title', 'Unknown')
        
        # Filter out non-supplier websites
        if not self._is_valid_supplier_url(url, title):
            return None
        
        try:
            log_info(f"Scraping: {url}", self.name)
            
            # Fetch website HTML
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract text (remove scripts and styles)
            for script in soup(["script", "style"]):
                script.decompose()
            full_text = soup.get_text(separator=' ', strip=True)
            
            # Extract emails using targeted context approach
            contact_email = self._extract_email(full_text)
            
            # Extract location using targeted context
            location = self._extract_location(full_text)
            
            # Use first 3000 chars for other info extraction
            text_for_llm = full_text[:3000]
            
            # Use LLM to extract structured data
            extracted_data = self._extract_supplier_info(text_for_llm, url, title, contact_email, location)
            
            return extracted_data
            
        except Exception as e:
            log_info(f"Scraping failed for {url}: {e}", self.name)
            return None
    
    def _extract_email(self, full_text: str):
        """Extract email using targeted context approach."""
        # Email-related keywords to search for
        email_keywords = [
            'contact', 'email', 'mail', 'reach', 'inquiry', 'enquiry',
            'sales', 'info', 'support', 'business', 'procurement',
            'get in touch', 'write to', 'send us', '@'
        ]
        
        # Split text into sentences
        sentences = re.split(r'[.!?\n]\s+', full_text)
        
        # Find sentences containing email keywords or @ symbol
        email_sentences = []
        for sentence in sentences:
            sentence_lower = sentence.lower()
            if any(keyword in sentence_lower for keyword in email_keywords):
                email_sentences.append(sentence.strip())
        
        # If no email-related sentences found, search entire text
        if not email_sentences:
            email_sentences = sentences[:50]  # Take first 50 sentences as fallback
        
        # Combine the context (first 10 email-related sentences)
        context = '. '.join(email_sentences[:10])
        
        # Extract all emails from this context using regex
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        all_emails = re.findall(email_pattern, context)
        
        if not all_emails:
            return None
        
        # Filter out junk emails
        junk_keywords = ['noreply', 'no-reply', 'donotreply', 'mailer-daemon', 
                        'postmaster', 'webmaster', 'admin@example', 'example.com']
        clean_emails = []
        for email in all_emails:
            if not any(junk in email.lower() for junk in junk_keywords):
                clean_emails.append(email)
        
        # Remove duplicates
        clean_emails = list(set(clean_emails))
        
        if not clean_emails:
            return None
        
        # If only one email, use it
        if len(clean_emails) == 1:
            return clean_emails[0]
        
        # If multiple emails, ask LLM to pick the best one from the context
        try:
            prompt = f"""From this contact information context, pick the BEST email address for procurement/sales inquiries.

Context:
{context[:1000]}

Available emails found: {', '.join(clean_emails)}

Rules:
- Pick email used for sales, procurement, business inquiries, or general contact
- Prefer: sales@, info@, contact@, business@, procurement@
- Avoid: careers@, hr@, press@, media@, marketing@
- Return ONLY the email address, nothing else

Best email:"""

            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["quick"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=50
            )
            
            chosen_email = response.choices[0].message.content.strip()
            
            # Clean up response
            chosen_email = chosen_email.replace('"', '').replace("'", '').strip()
            
            # Validate it's actually one of our emails
            if chosen_email in clean_emails:
                return chosen_email
            else:
                # LLM gave weird response, use first clean email
                return clean_emails[0]
                
        except Exception as e:
            log_error(f"Email selection failed: {e}", self.name)
            return clean_emails[0]  # Fallback to first
    
    def _extract_location(self, full_text: str):
        """Extract location using targeted context approach."""
        # Location keywords to search for
        location_keywords = [
            'mumbai', 'delhi', 'bangalore', 'pune', 'chennai', 'hyderabad', 
            'kolkata', 'ahmedabad', 'surat', 'jaipur', 'lucknow', 'kanpur',
            'india', 'address', 'located', 'based in', 'location', 
            'office', 'headquarters', 'facility', 'plant', 'warehouse', 'hq'
        ]
        
        # Split text into sentences
        sentences = re.split(r'[.!?]\s+', full_text)
        
        # Find sentences containing location keywords
        location_sentences = []
        for sentence in sentences:
            sentence_lower = sentence.lower()
            if any(keyword in sentence_lower for keyword in location_keywords):
                location_sentences.append(sentence.strip())
        
        # If no location-related sentences found
        if not location_sentences:
            return "Unknown"
        
        # Take first 5 location-related sentences (or all if less than 5)
        context = '. '.join(location_sentences[:5])
        
        # Ask LLM to extract location from this targeted context
        try:
            prompt = f"""Extract the MAIN headquarters city from this text. Return ONLY ONE city name.

Rules:
- If multiple cities mentioned, pick the headquarters/main office
- Look for keywords: "headquarters", "head office", "based in", "registered office"
- Return ONLY the city name (one word or two words max)
- Examples of good answers: "Mumbai", "New Delhi", "Bangalore"
- Examples of bad answers: "Mumbai Delhi Chennai", "India", "Multiple locations"

Text:
{context}

Return ONLY ONE city name, nothing else. If truly no specific city found, return "Unknown"."""

            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["reasoning"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=10  # Force short response
            )
            
            location = response.choices[0].message.content.strip()
            
            # Clean up response
            location = location.replace('"', '').replace("'", '').strip()
            
            # Validation: Should be max 2 words (e.g., "New Delhi")
            word_count = len(location.split())
            if word_count > 2:
                # LLM gave multiple cities, take first word only
                location = location.split()[0]
            
            return location if location and location != "Unknown" else "Unknown"
            
        except Exception as e:
            log_error(f"Location extraction failed: {e}", self.name)
            return "Unknown"
    
    def _extract_supplier_info(self, website_text: str, url: str, title: str, contact_email: str, location: str):
        """Use Groq LLM to extract structured supplier information."""
        prompt = f"""You are analyzing a supplier's website. Extract the following information from the text below.

Website Title: {title}
Website URL: {url}

Website Text:
{website_text}

Extract and return ONLY a JSON object with these fields:
{{
    "company_name": "extracted company name or use title",
    "contact_phone": "phone if found, else null",
    "years_in_business": estimated years as integer or null,
    "has_iso_certification": true/false (look for ISO 9001, ISO 14001, or any ISO certification),
    "certifications": "list certifications mentioned or empty string",
    "rating": estimated rating 3.0-5.0 based on website professionalism
}}

Return ONLY valid JSON, no explanation."""

        try:
            response = groq.client.chat.completions.create(
                model=GROQ_MODELS["quick"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Parse JSON
            if result_text.startswith('```json'):
                result_text = result_text.replace('```json', '').replace('```', '').strip()
            
            supplier_data = json.loads(result_text)
            supplier_data['url'] = url
            supplier_data['website'] = url
            supplier_data['source_title'] = title
            supplier_data['supplier_name'] = supplier_data.get('company_name', title)
            supplier_data['contact_email'] = contact_email  # Use already extracted email
            supplier_data['location'] = location  # Use already extracted location
            
            return supplier_data
            
        except Exception as e:
            log_error(f"LLM extraction failed: {e}", self.name)
            # Return basic fallback data
            return {
                'company_name': title,
                'supplier_name': title,
                'url': url,
                'website': url,
                'contact_email': contact_email,
                'contact_phone': None,
                'years_in_business': None,
                'has_iso_certification': False,
                'certifications': '',
                'location': location,
                'rating': 0,
                'source_title': title
            }
    
    def _calculate_quality_scores(self, suppliers: list):
        """Calculate quality score for each supplier."""
        for supplier in suppliers:
            score = 0
            
            # Rating (0-20 points)
            rating = supplier.get('rating', 3)
            score += rating * 4
            
            # ISO Certification (5 points)
            if supplier.get('has_iso_certification'):
                score += 5
            
            # Years in business (max 10 points - better scaling)
            years = supplier.get('years_in_business')
            if years and years > 0:
                score += min(years // 2, 10)  # Divide by 2, cap at 10
            
            # Contact info (5 points)
            if supplier.get('contact_email') or supplier.get('contact_phone'):
                score += 5
            
            supplier['quality_score'] = round(score, 0)
            
            # Determine quality level
            if score >= 28:
                quality_level = 'High Quality'
            elif score >= 18:
                quality_level = 'Medium Quality'
            else:
                quality_level = 'Low Quality'
            
            supplier['quality_level'] = quality_level
            
            if score >= 28:
                supplier['risk_level'] = 'Low Risk'
            elif score >= 18:
                supplier['risk_level'] = 'Medium Risk'
            else:
                supplier['risk_level'] = 'High Risk'
            
            # Generate natural language summary using LLM
            # Generate natural language summary using LLM
            try:
                if supplier.get('is_historical'):
                    prompt = f"""Write a brief 1-2 sentence explanation summarizing this supplier's historical performance for {supplier.get('products_supplied')}. 
Use the following historical data:
- Past Exceptions/Issues: {supplier.get('historical_exception')}
- Compensation provided: {supplier.get('historical_compensation')}
- Past Quantity Ordered: {supplier.get('quantity_bought')} units
- Unit Price: ₹{supplier.get('unit_price')}
- Total Spend: ₹{supplier.get('total_price')}

Write a concise, natural sentence explaining their reliability and cost. Do not write a whole paragraph."""
                else:
                    prompt = f"""Write a brief one-sentence explanation for why this supplier has {quality_level}.

Supplier details:
- ISO Certified: {"Yes" if supplier.get('has_iso_certification') else "No"}
- Rating: {rating}/5
- Years in business: {years if years else "Unknown"}
- Contact available: {"Yes" if supplier.get('contact_email') or supplier.get('contact_phone') else "No"}
- Quality Score: {score}/35

Write a natural sentence explaining the quality level. Be concise and specific."""

                response = groq.client.chat.completions.create(
                    model=GROQ_MODELS["quick"],
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=150
                )
                
                supplier['summary'] = response.choices[0].message.content.strip()
                
            except Exception as e:
                log_error(f"Summary generation failed: {e}", self.name)
                supplier['summary'] = f"{quality_level} - Limited information available"
        
        return suppliers
    
    def format_supplier_info(self, suppliers: list) -> str:
        """Format supplier list for display."""
        output = ""
        for i, s in enumerate(suppliers, 1):
            name = s.get('supplier_name', s.get('company_name', 'Unknown'))
            output += f"{i}. **{name}**\n"
            output += f"   URL: {s.get('url', s.get('website', 'N/A'))}\n"
            output += f"   Location: {s.get('location', 'Unknown')}\n"
            
            # Contact info
            contact_email = s.get('contact_email')
            if contact_email:
                output += f"   Contact: {contact_email}\n"
            else:
                output += f"   Contact: No contact available\n"
            
            # Quality level and summary (no score shown)
            output += f"   Quality: {s.get('quality_level', 'Unknown')}\n"
            output += f"   {s.get('summary', 'No details available')}\n"
            output += "\n"
        return output


if __name__ == "__main__":
    print("="*60)
    print("Testing Agent 4 - Supplier Discovery & Risk Assessor")
    print("="*60)
    
    agent = SupplierDiscovery()
    
    # Test 1: Search for M8 Screws suppliers
    print("\n" + "="*60)
    print("Test 1: Search for M8 Screws Suppliers in India")
    print("-" * 60)
    
    result1 = agent.execute('ITM001', 'M8 Screws', location='India', top_n=5)
    
    if result1:
        print(f"\n✓ Search Query: {result1['search_query']}")
        print(f"✓ Suppliers Found: {result1['suppliers_found']}")
        print(f"✓ Top Suppliers Returned: {len(result1['suppliers'])}")
        print(f"\nSupplier Details:")
        print(agent.format_supplier_info(result1['suppliers']))
    else:
        print("✗ Supplier search failed or no suppliers found")
    
    # Test 2: Search for Electric Motors suppliers
    print("\n" + "="*60)
    print("Test 2: Search for Electric Motors Suppliers in India")
    print("-" * 60)
    
    result2 = agent.execute('ITM009', 'Electric Motors', location='India', top_n=5)
    
    if result2:
        print(f"\n✓ Search Query: {result2['search_query']}")
        print(f"✓ Suppliers Found: {result2['suppliers_found']}")
        print(f"✓ Top Suppliers Returned: {len(result2['suppliers'])}")
        print(f"\nSupplier Details:")
        print(agent.format_supplier_info(result2['suppliers']))
    else:
        print("✗ Supplier search failed or no suppliers found")
    
    # Test 3: Output structure verification
    print("\n" + "="*60)
    print("Test 3: Output Structure Verification")
    print("-" * 60)
    
    if result1:
        print("\nChecking required output fields:")
        required_fields = ['item_code', 'item_name', 'search_query', 
                          'suppliers_found', 'suppliers']
        for field in required_fields:
            status = "✓" if field in result1 else "✗"
            print(f"  {status} {field}")
        
        if result1['suppliers']:
            print("\nChecking supplier record fields:")
            supplier_fields = ['supplier_name', 'contact_email', 'website', 
                             'rating', 'location', 'quality_score', 'summary']
            first_supplier = result1['suppliers'][0]
            for field in supplier_fields:
                status = "✓" if field in first_supplier else "✗"
                value = first_supplier.get(field, 'Missing')
                print(f"  {status} {field}: {value}")
        
        # Test 4: Email extraction verification
        print("\n" + "="*60)
        print("Test 4: Email Extraction Verification")
        print("-" * 60)
        
        print("\nEmail extraction results:")
        emails_found = 0
        for i, sup in enumerate(result1['suppliers'], 1):
            email = sup.get('contact_email')
            if email:
                emails_found += 1
            status = "✓" if email else "✗"
            print(f"  {status} {sup.get('supplier_name', 'Unknown')}: {email if email else 'No email found'}")
        
        print(f"\nTotal emails found: {emails_found}/{len(result1['suppliers'])}")
        
        # Test 5: Score verification
        print("\n" + "="*60)
        print("Test 5: Scoring Verification (Max 35 points)")
        print("-" * 60)
        
        print("\nScores for all suppliers:")
        for i, sup in enumerate(result1['suppliers'], 1):
            score = sup.get('quality_score', 0)
            print(f"  {i}. {sup.get('supplier_name', 'Unknown')}")
            print(f"     Quality Score: {int(score)}/35")
            print(f"     Quality Level: {sup.get('quality_level', 'Unknown')}")
            print(f"     Summary: {sup.get('summary', 'N/A')}")
        
        # Verify sorting (highest score first)
        scores = [s.get('quality_score', 0) for s in result1['suppliers']]
        if scores == sorted(scores, reverse=True):
            print("\n  ✓ Suppliers correctly sorted by quality score (best first)")
        else:
            print("\n  ✗ Suppliers NOT sorted correctly")
        
        # Check if scores are within valid range
        max_score = max(scores) if scores else 0
        min_score = min(scores) if scores else 0
        if max_score <= 35 and min_score >= 0:
            print(f"  ✓ All scores within valid range (0-35)")
        else:
            print(f"  ✗ Invalid scores detected (Max: {max_score}, Min: {min_score})")
    
    # Test 6: Location extraction verification
    print("\n" + "="*60)
    print("Test 6: Location Extraction Verification")
    print("-" * 60)
    
    if result1:
        print("\nLocation extraction results:")
        locations_found = 0
        for i, sup in enumerate(result1['suppliers'], 1):
            loc = sup.get('location', 'Unknown')
            if loc and loc != 'Unknown':
                locations_found += 1
            status = "✓" if loc != 'Unknown' else "✗"
            print(f"  {status} {sup.get('supplier_name', 'Unknown')}: {loc}")
        
        print(f"\nTotal locations found: {locations_found}/{len(result1['suppliers'])}")
    
    # Test 7: URL filtering verification
    print("\n" + "="*60)
    print("Test 7: URL Filtering Verification")
    print("-" * 60)
    
    if result1:
        print("\nChecking if non-supplier sites were filtered:")
        for i, sup in enumerate(result1['suppliers'], 1):
            url = sup.get('url', '')
            # Check if any blacklisted domains made it through
            blacklist_check = ['indiamart', 'tradeindia', 'justdial', 'blog', 'news']
            has_blacklist = any(b in url.lower() for b in blacklist_check)
            status = "✗" if has_blacklist else "✓"
            print(f"  {status} {sup.get('supplier_name', 'Unknown')}: {url}")
    
    print("\n" + "="*60)
    print("Agent 4 testing complete")
    print("="*60)
