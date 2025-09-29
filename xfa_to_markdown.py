#!/usr/bin/env python3
"""
XFA PDF to Markdown Converter
Extracts XFA form data and outputs a formatted Markdown report

Usage: python3 xfa_to_markdown.py input.pdf [output.md]
"""

import pikepdf
from xml.etree import ElementTree as ET
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter

class XFAToMarkdownConverter:
    """Convert XFA PDF data to formatted Markdown"""
    
    def __init__(self):
        self.form_data = {}
        self.form_structure = {}
        self.field_counts = Counter()
        
    def extract_xfa_data(self, pdf_path):
        """Extract XFA datasets from PDF"""
        try:
            with pikepdf.open(pdf_path) as pdf:
                print(f"📖 Opening PDF: {pdf_path}")
                
                # Check for XFA
                acro = pdf.Root.get('/AcroForm', None)
                if not acro or '/XFA' not in acro:
                    return None, "No XFA form found in PDF"

                xfa = acro['/XFA']
                
                if not isinstance(xfa, pikepdf.Array):
                    return None, "XFA structure not recognized"
                
                print(f"🔍 Found XFA with {len(xfa)} components")
                
                # Extract datasets
                for i in range(0, len(xfa), 2):
                    if i + 1 < len(xfa):
                        name = str(xfa[i])
                        stream = xfa[i+1]
                        
                        if name.lower() == 'datasets':
                            print(f"📊 Extracting datasets...")
                            data = bytes(stream.read_bytes())
                            print(f"✅ Extracted {len(data):,} bytes of form data")
                            return data, None
                
                return None, "No datasets found in XFA"
                
        except Exception as e:
            return None, f"Error extracting XFA data: {e}"
    
    def parse_xml_data(self, xml_data):
        """Parse XML data and organize form information"""
        try:
            root = ET.fromstring(xml_data)
            print(f"🔧 Parsing XML data...")
            
            # Collect all elements with text content
            form_fields = defaultdict(list)
            field_hierarchy = defaultdict(set)
            
            for elem in root.iter():
                # Clean tag name (remove namespace)
                tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                
                if elem.text and elem.text.strip():
                    text_content = elem.text.strip()
                    form_fields[tag_name].append(text_content)
                    self.field_counts[tag_name] += 1
                    
                    # Track parent-child relationships (skip for now - getparent not available in standard ET)
                    # Note: Parent-child tracking would require lxml for getparent() method
            
            self.form_data = dict(form_fields)
            self.form_structure = dict(field_hierarchy)
            
            print(f"✅ Parsed {len(self.form_data)} field types with {sum(self.field_counts.values())} total values")
            return True
            
        except ET.ParseError as e:
            print(f"❌ XML parsing error: {e}")
            return False
        except Exception as e:
            print(f"❌ Error parsing XML: {e}")
            return False
    
    def categorize_fields(self):
        """Categorize fields by type and importance"""
        categories = {
            'Personal Information': [
                'GivenName', 'FamilyName', 'MiddleName', 'DateOfBirth', 
                'PlaceOfBirth', 'CountryOfBirth', 'Gender', 'MaritalStatus'
            ],
            'Contact Information': [
                'MailingAddress', 'PhoneNumber', 'EmailAddress', 'Address',
                'City', 'Province', 'PostalCode', 'Country'
            ],
            'Identity Documents': [
                'PassportNumber', 'PassportCountry', 'PassportIssueDate', 
                'PassportExpiryDate', 'NationalID', 'IdentityDocument'
            ],
            'Application Details': [
                'ApplyingCategory', 'PurposeOfVisit', 'IntendedDateOfArrival',
                'IntendedLengthOfStay', 'VisaType', 'ApplicationType'
            ],
            'Background Information': [
                'Education', 'Occupation', 'EmploymentHistory', 'Language',
                'AbleCommunicateEnglishOrFrench', 'PreviousApplication'
            ],
            'Financial Information': [
                'FundsAvailable', 'FinancialSupport', 'Income', 'Employment'
            ]
        }
        
        categorized = defaultdict(dict)
        uncategorized = {}
        
        for field_name, values in self.form_data.items():
            categorized_field = False
            
            for category, field_list in categories.items():
                if any(field_name.lower().find(cat_field.lower()) != -1 for cat_field in field_list):
                    categorized[category][field_name] = values
                    categorized_field = True
                    break
            
            if not categorized_field:
                uncategorized[field_name] = values
        
        return dict(categorized), uncategorized
    
    def generate_markdown(self, pdf_path, output_path):
        """Generate formatted Markdown report"""
        pdf_name = Path(pdf_path).name
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        categorized_fields, uncategorized_fields = self.categorize_fields()
        
        # Start building markdown content
        md_content = []
        
        # Header
        md_content.extend([
            f"# XFA Form Data Report",
            f"",
            f"**Source PDF:** `{pdf_name}`  ",
            f"**Generated:** {timestamp}  ",
            f"**Total Fields:** {len(self.form_data)}  ",
            f"**Total Values:** {sum(self.field_counts.values())}  ",
            f"",
            "---",
            ""
        ])
        
        # Table of Contents
        md_content.extend([
            "## 📋 Table of Contents",
            ""
        ])
        
        toc_items = []
        if categorized_fields:
            for category in categorized_fields.keys():
                toc_items.append(f"- [{category}](#{category.lower().replace(' ', '-')})")
        
        if uncategorized_fields:
            toc_items.append("- [Other Fields](#other-fields)")
        
        toc_items.extend([
            "- [Field Statistics](#field-statistics)",
            "- [Form Structure](#form-structure)"
        ])
        
        md_content.extend(toc_items)
        md_content.extend(["", "---", ""])
        
        # Categorized fields
        for category, fields in categorized_fields.items():
            if not fields:
                continue
                
            md_content.extend([
                f"## 👤 {category}",
                ""
            ])
            
            for field_name, values in sorted(fields.items()):
                md_content.append(f"### {field_name}")
                
                if len(values) == 1:
                    md_content.append(f"**Value:** `{values[0]}`")
                else:
                    md_content.append(f"**Options/Values ({len(values)}):**")
                    for i, value in enumerate(values[:20], 1):  # Limit to first 20
                        md_content.append(f"{i}. `{value}`")
                    if len(values) > 20:
                        md_content.append(f"... and {len(values) - 20} more")
                
                md_content.extend(["", ""])
        
        # Uncategorized fields
        if uncategorized_fields:
            md_content.extend([
                "## 📝 Other Fields",
                ""
            ])
            
            for field_name, values in sorted(uncategorized_fields.items()):
                md_content.append(f"### {field_name}")
                
                if len(values) == 1:
                    md_content.append(f"**Value:** `{values[0]}`")
                elif len(values) <= 10:
                    md_content.append(f"**Values ({len(values)}):**")
                    for value in values:
                        md_content.append(f"- `{value}`")
                else:
                    md_content.append(f"**Values ({len(values)}):** `{', '.join(values[:5])}` ... and {len(values) - 5} more")
                
                md_content.extend(["", ""])
        
        # Field Statistics
        md_content.extend([
            "## 📊 Field Statistics",
            "",
            "| Field Name | Value Count | Sample Value |",
            "|------------|-------------|--------------|"
        ])
        
        for field_name, count in self.field_counts.most_common(20):
            sample_value = self.form_data[field_name][0][:50] if self.form_data[field_name] else "N/A"
            if len(sample_value) == 50:
                sample_value += "..."
            md_content.append(f"| `{field_name}` | {count} | `{sample_value}` |")
        
        if len(self.field_counts) > 20:
            md_content.append(f"| ... | ... | *{len(self.field_counts) - 20} more fields* |")
        
        md_content.extend(["", ""])
        
        # Form Structure
        if self.form_structure:
            md_content.extend([
                "## 🏗️ Form Structure",
                "",
                "Parent-child field relationships:",
                ""
            ])
            
            for parent, children in sorted(self.form_structure.items()):
                if children:
                    md_content.append(f"**{parent}**")
                    for child in sorted(children):
                        md_content.append(f"  - {child}")
                    md_content.append("")
        
        # Footer
        md_content.extend([
            "---",
            "",
            f"*Report generated by XFA to Markdown Converter*  ",
            f"*Source: {pdf_name}*  ",
            f"*Generated: {timestamp}*"
        ])
        
        # Write to file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md_content))
        
        print(f"📄 Markdown report saved to: {output_path}")
        return output_path

def main():
    parser = argparse.ArgumentParser(
        description='Extract XFA form data from PDF and generate Markdown report',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 xfa_to_markdown.py form.pdf
  python3 xfa_to_markdown.py form.pdf report.md
  python3 xfa_to_markdown.py "imm5257e (1).pdf" imm5257e_report.md
        """
    )
    
    parser.add_argument('pdf_path', help='Path to XFA PDF file')
    parser.add_argument('output_path', nargs='?', help='Output Markdown file path (optional)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    # Validate input file
    if not os.path.exists(args.pdf_path):
        print(f"❌ Error: PDF file not found: {args.pdf_path}")
        sys.exit(1)
    
    # Generate output path if not provided
    if not args.output_path:
        pdf_path = Path(args.pdf_path)
        args.output_path = pdf_path.parent / f"{pdf_path.stem}_report.md"
    
    print("🚀 XFA PDF to Markdown Converter")
    print("=" * 40)
    
    # Initialize converter
    converter = XFAToMarkdownConverter()
    
    # Extract XFA data
    xml_data, error = converter.extract_xfa_data(args.pdf_path)
    if error:
        print(f"❌ {error}")
        sys.exit(1)
    
    # Parse XML data
    if not converter.parse_xml_data(xml_data):
        print("❌ Failed to parse XML data")
        sys.exit(1)
    
    # Generate Markdown report
    try:
        output_file = converter.generate_markdown(args.pdf_path, args.output_path)
        print("=" * 40)
        print(f"✅ Success! Report generated:")
        print(f"📁 {output_file}")
        print(f"📊 {len(converter.form_data)} field types extracted")
        print(f"📈 {sum(converter.field_counts.values())} total values processed")
        
    except Exception as e:
        print(f"❌ Error generating report: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
