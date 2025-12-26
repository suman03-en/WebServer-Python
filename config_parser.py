import re
from typing import List,Tuple,Union

#Each token is represented as a tuple: (type,value)
Token = Tuple[str, str]

class SimpleConfigLexer:
    """
    A basic lexer for NGINX-style config files.
    It recognizes:
    - comments (starting with #)
    - symbols: { } ;
    - quoted strings
    - plain words: directives, numbers, paths
    """
    TOKEN_PATTERNS = [
        ("COMMENT", r"#.*"),
        ("LBRACE", r"\{"),
        ("RBRACE", r"\}"),
        ("SEMICOLON", r";"),
        ("STRING", r'"[^"]*"'),
        ("WORD", r"[a-zA-Z0-9_./\-]+"),
        ("WHITESPACE", r"[ \t\r\n]+"),
    ]
    
    def __init__(self,config_text: str):
        self.config_text = config_text
        self.tokens = self.tokenize()
    
    def tokenize(self) -> List[Token]:
        pattern = "|".join(f"(?P<{name}>{regex})" for name,regex in self.TOKEN_PATTERNS)
        token_re = re.compile(pattern)

        pos = 0
        tokens: List[Token] = []

        while pos < len(self.config_text):
            match = token_re.match(self.config_text,pos)
            if not match:
                raise SyntaxError(f"Unexpected character at position {pos}: {self.config_text[pos]!r}")
            kind = match.lastgroup
            value = match.group()

            if kind in ("WHITESPACE","COMMENT"):
                pass #skip it
            elif kind == "STRING":
                tokens.append((kind,value))
            else:
                tokens.append((kind,value))
            pos = match.end()
        
        return tokens
    
#optional just to visualize
def visualize_token_stream(tokens: List[Token]) -> None:
    indent = 0
    for token_type,value in tokens:
        if token_type == "RBRACE":
            indent -= 1
        print("    "*indent + f"{token_type:10}: {value}")
        if token_type == "LBRACE":
            indent += 1

ConfigDict = dict[str,Union[str,"ConfigDict",list]]

class SimpleConfigParser:
    """
    Parses a list of tokens into a nested configuration dictionary.

    This parser assumes a simplified NGINX-style format where:
    - Each line is either a directive (ends with ';') or a block (enclosed in { ... }).
    - Blocks can be nested.
    - Blocks may take one argument (e.g. 'location / { ... }').
    """   

    def __init__(self,tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0 #keeps track of which token we're currently parsing

    def parse(self) -> ConfigDict:
        """
        Entry point: parse the full list of tokens and return a nested dictionary.
        This handles the top-level of the configuration (e.g., the main context).
        """
        return self._parse_block()
    
    def _parse_block(self) -> ConfigDict:
        """
        Parses a block of configuration. This is a recursive function:
        - Called when entering a new { ... } block.
        - Returns a dictionary representing the contents of that block.
        """
        config: ConfigDict = {} 
        while self.pos < len(self.tokens):
            token_type, token_value = self.tokens[self.pos]

            if token_type == "RBRACE":
                self.pos += 1
                return config
            
            if token_type != "WORD":
                raise SyntaxError(f"Expected directive name(WORD),but got {token_type} '{token_value}'")
            
            key = token_value
            self.pos += 1

            args = []

            while self.pos < len(self.tokens):
                t_type, t_value = self.tokens[self.pos]

                if t_type == "LBRACE":
                    if len(args) > 1:
                        raise SyntaxError(f"Block '{key}' can only have one argument. Found: {args}")
                    self.pos += 1 # consume the '{'
                    block = self._parse_block()

                    if args:
                        arg_key = args[0]
                        if key not in config:
                            config[key] = {}
                        if not isinstance(config[key],dict):
                             raise SyntaxError(f"Cannot nest block under non-dictionary directive '{key}'")
                        config[key][arg_key] = block
                    else:
                        if key in config:
                            if isinstance(config[key],list):
                                config[key].append(block)
                            else:
                                config[key] = [config[key],block]
                        else:
                            config[key] = block
                    break 
                
                elif t_type == "SEMICOLON":
                    # We've reached the end of a simple directive like:
                    # listen 8080;
                    self.pos += 1
                    value = args[0] if len(args) == 1 else args
                    # If the same directive appears multiple times, store values in a list.
                    if key in config:
                        if isinstance(config[key],list):
                            config[key].append(value)
                        else:
                            config[key] = [config[key], value]
                    else:
                        config[key] = value

                    break

                elif t_type != "WORD":
                    raise SyntaxError(f"Unexpected token in argument list: {t_type} '{t_value}'")
                
                else:
                    args.append(t_value)
                    self.pos += 1
            else:
                raise SyntaxError(f"Unexpected end of input after key '{key}' — expected ';' or '{{'.")
        return config
                      
class ServerConfig:
    """
    Wraps parsed configuration into a higher-level object with useful accessors.
    This class makes it easier to access settings like ports and routes.

    Expected format: output of SimpleConfigParser.parse()
    """
    def __init__(self,config_dict: dict):
        self.config = config_dict 
    
    def get_servers(self) -> list[dict]:
        """
        Returns a list of server blocks inside the http block.

        Handles:
        - No 'http' block present
        - One or more server blocks (as object or list)
        """ 
        http_block = self.config.get("http",{})
        servers = http_block.get("server",[])

        if isinstance(servers,dict):
            return [servers] #single server block
        
        return servers
    
    @property
    def listen_ports(self) -> list[int]:
        """
        Extracts all port numbers from server blocks.
        Assumes port is defined via 'listen' directive.
        """
        ports = []
        for server in self.get_servers():
            port = server.get("listen")
            if port:
                try:
                    ports.append(int(port))
                except ValueError:
                    raise ValueError(f"Invalid port number: {port!r}")
        return ports
    
    @property
    def routes(self) -> dict[int, dict[str, str]]:
        """
        Returns a nested dictionary mapping:
        {port: {path: root_dir}} for each server block.
        """
        mapping = {}
        for server in self.get_servers():
            port = int(server.get("listen", 80))
            locations = server.get("location", {})
            if isinstance(locations, dict):  # single location
                locations = [locations]
            route_map = {}

            for loc in locations:
                for path, inner in loc.items():
                    if isinstance(inner, dict) and "root" in inner:
                        route_map[path] = inner["root"]
            mapping[port] = route_map
        print(mapping)
        return mapping


def load_config(path: str) -> ServerConfig:
    """
    Reads a config file, tokenizes and parses it, then wraps in ServerConfig.
    """
    with open(path,"r",encoding="utf-8") as f:
        config_text = f.read()
    
    lexer = SimpleConfigLexer(config_text)
    parser = SimpleConfigParser(lexer.tokens)
    parsed_dict = parser.parse()
    return ServerConfig(parsed_dict)
