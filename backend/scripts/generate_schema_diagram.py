import re
import os

def generate_mermaid(schema_path):
    with open(schema_path, 'r') as f:
        content = f.read()

    models = re.findall(r'model (\w+) {([\s\S]*?)}', content)
    
    mermaid = "erDiagram\n"
    
    for model_name, model_content in models:
        fields = re.findall(r'^\s+(\w+)\s+(\w+)(\?|\[\])?.*', model_content, re.MULTILINE)
        
        # Add model and fields
        mermaid += f"    {model_name} {{\n"
        for field_name, field_type, modifier in fields:
            if not modifier or modifier == '?':
                mermaid += f"        {field_type} {field_name}\n"
        mermaid += "    }\n"
        
        # Add relations (simplified)
        relations = re.findall(r'(\w+)\s+(\w+)\s+@relation\(fields: \[(\w+)\], references: \[(\w+)\].*\)', model_content)
        for field_name, target_model, local_id, remote_id in relations:
            # Determine relationship type (simplified)
            # Find the other side if it exists
            # For now, just show a general relationship
            mermaid += f"    {model_name} ||--o{{ {target_model} : \"{local_id}->{remote_id}\"\n"
            
    return mermaid

if __name__ == "__main__":
    schema_file = os.path.join(os.path.dirname(__file__), '../../prisma/schema.prisma')
    print(generate_mermaid(schema_file))
