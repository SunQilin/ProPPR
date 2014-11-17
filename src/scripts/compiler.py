import collections
import sys
import string

import util
import symtab as syt

# Compile prolog rules in one of these sample formats to a variant of
# a Warren abstract machine.
#
# p(X,Y) :- q(X,Z), r(Z,X).         # normal prolog clause
# p(X,Y,Z) :- .                     # unit clause
# p(X,Y) :- q(X,Z) {f(Y,X)}.        # normal prolog clause plus a 'feature'  
# p(X,Y) :- q(X,Z) {f(Y,X),g(Y)}.   # multiple 'features'  
# p(X,Y) :- q(X,Z) {f(W) : g(Y,W)}. # features geberated by a 'findall'
#                                   #  ie for all solutions of g(Y,W), 
#                                   #  produce a feature f(W)

##############################################################################
## data structures to encode rules
##############################################################################

def isProcessedConstant(a):
    return not isProcessedVariable(a)

def isProcessedVariable(a):
    return type(a)==type(0)

def isVariableAtom(a):
    return a[0].isupper() or a[0]=='_' 

class Goal(object):
    """A prolog goal, eg brotherOf(X,Y)."""
    def __init__(self,functor,args):
        self.functor = functor
        self._setArgs(args)
        
    def _setArgs(self,args):
        self.args = args
        self.arity = len(args)

    def __str__(self):
        if self.arity: return "%s(%s)" % (self.functor,",".join(map(str,self.args)))
        else: return self.functor

class Rule(object):
    """A prolog rule.  The lhs is a goal, the rhs a list of goals, so the
    rule's format is "lhs :- rhs."  The features for a rule are, in
    general, of the form "features : findall", where 'findall' and
    'features' are lists of goals.  Features are produced as follows:
    after binding the head of the rule, you find all solutions to the
    'findall' part (the "generator"), and for each solution, create a
    feature corresponding to a bound version of each goal g in
    'features'.
    """

    def __init__(self,lhs,rhs,features=None,findall=None):
        self.lhs = lhs
        self.rhs = rhs
        self.features = features
        self.findall = findall
        self.variableList = None
        self.nvars = -1

    def variabilize(self):
        """Convert the variables to integer indices, -1,-2, ... and save their
        original names in "variableList", and the number of distinct
        variables in 'nvars."""
        if self.nvars>=0:
            pass #already done
        else:
            varTab = syt.SymbolTable()
            def convertArgs(args):
                return map(lambda a: -varTab.getId(a) if isVariableAtom(a) else a, args)
            def convertGoal(g):
                return Goal(g.functor, convertArgs(g.args))
            if self.lhs: self.lhs = convertGoal(self.lhs)
            self.rhs = map(convertGoal, self.rhs)
            if self.features:
                self.features = map(convertGoal, self.features)
            if self.findall:
                self.findall = map(convertGoal, self.findall)                
            self.variableList = varTab.getSymbolList()
            self.nvars = len(self.variableList)

    def __str__(self):
        vars = "  #v:"+str(self.variableList) if self.variableList else ''
        findalls = ' : '+",".join(map(str,self.findall)) if self.findall else ''
        features = ' {' + ",".join(map(str,self.features)) + findalls + '}' if self.features else ''
        return str(self.lhs) + " :- " + ", ".join(map(str,self.rhs)) + features + vars + '.'

class RuleCollection(object):
    """A set of prolog rules, indexed by functor and arity."""
    
    def __init__(self):
        self.index = collections.defaultdict(list)
    
    def add(self,r):
        key = self._key(r.lhs)
        self.index[key] += [r]

    def _key(self,g):
        return '%s/%d' % (g.functor,g.arity) 

    def listing(self):
        for key in self.index:
            print'% rules for',key
            for r in self.index[key]:
                print r

##############################################################################
## the parser
##############################################################################

from pyparsing import Word, CharsNotIn, alphas, alphanums, delimitedList, nestedExpr, Optional, Group, QuotedString

atomNT = Word( alphanums+"_" ) |  QuotedString(quoteChar="'",escChar="\\")
goalNT = atomNT + Optional("(" + delimitedList(atomNT) + ")")
goalListNT = Optional(delimitedList(Group(goalNT)))
featureFindAllNT = Optional(":" + delimitedList(Group(goalNT)))
featureTemplateNT = delimitedList(Group(goalNT))
featureBlockNT = Optional("{" + featureTemplateNT('ftemplate') + featureFindAllNT('ffindall') + "}")
ruleNT = goalNT("lhs") + ":-" + goalListNT("rhs") +  featureBlockNT("features") + "."

class Parser(object):

    @staticmethod
    def _convertGoal(ptree):
        return Goal(ptree[0], ptree[2:-1])

    @staticmethod
    def _convertRule(ptree):
        if 'rhs' in ptree: 
            tmpRhs = map(Parser._convertGoal, ptree['rhs'].asList())
        else: 
            tmpRhs = []
        if not 'features' in ptree:
            return Rule(Parser._convertGoal(ptree['lhs']),tmpRhs,None,None) 
        else:
            if not 'ffindall' in ptree:
                featureList = ptree['ftemplate'].asList()
                tmpFeatures = map(Parser._convertGoal, featureList)
                return Rule(Parser._convertGoal(ptree['lhs']),tmpRhs,tmpFeatures,None) 
            else:
                featureList = ptree['ftemplate'].asList()
                tmpFeatures = map(Parser._convertGoal, featureList)
                findallList = ptree['ffindall'].asList()[1:]
                tmpFindall = map(Parser._convertGoal, findallList)                
                return Rule(Parser._convertGoal(ptree['lhs']),tmpRhs,tmpFeatures,tmpFindall) 

    @staticmethod
    def parseGoal(s):
        """Convert a string to a goal."""
        return Parser._convertGoal(goalNT.parseString(s))
	
    @staticmethod
    def parseGoalList(s):
        """Convert a string to a goal list."""
        return map(Parser._convertGoal, goalListNT.parseString(s).asList())
		
    @staticmethod
    def parseRule(s):
        """Convert a string to a rule."""
        return Parser._convertRule(ruleNT.parseString(s))

    @staticmethod
    def parseQuery(s):
        """Convert a string to a headless rule (no lhs)"""
        result = Parser.parseRule('dummy :- %s\n' % s)
        result.lhs = None
        return result

    @staticmethod
    def parseFile(file,rules = None):
        """Extract a series of rules from a file."""
        if not rules: rules = RuleCollection()
        buf = ""
        for line in open(file,'r'):
            if not line[0]=='#':
                buf += line
        try:
            for (ptree,lo,hi) in ruleNT.scanString(buf):
                rules.add(Parser._convertRule(ptree))
            return rules
        except KeyError:
            print 'error near ',lo,'in',file
        return rules

##############################################################################
## A compiled program
##############################################################################

class Program(object):
    """Holds a modified Warran abstract machine program, consisting of:

    1)instructions = a list of tuples (opcode,arg1,...)

    2) labels = a defaultdict such that labels["p/n"] is a list of
     addresses (ie, indices in instructions) where the instructions
     for the clauses of p/n start.

    3) instLabels = a dict such that instLabels[i] is the label
    given to instruction i, if there is such a label.
    """
    def __init__(self):
        self.instructions = []
        self.labels = collections.defaultdict(list)
        self.instLabels = {}

    def append(self,instr):
        """Append a single instruction."""
        self.instructions.append(instr)

    def truncateTo(self,addr):
        """Remove all instructions past given address."""
        self.instructions = self.instructions[:addr]

    def insertLabel(self,key):
        addr = len(self.instructions)
        self.labels[key].append(addr)
        self.instLabels[addr] = key

    def ithInstructionAsString(self,i):
        inst = self.instructions[i]
        return '%-3d %8s  %s %s' % (i,self.instLabels.get(i,''),inst[0],inst[1:])

    def listing(self,lo=0):
        for i in range(lo,len(self.instructions)):
            print self.ithInstructionAsString(i)

    def sourceListing(self):
        for i in range(len(self.instructions)):
            if self.instructions[i][0]=='comment':
                print self.instructions[i][1]

    def serialization(self,lo=0):
        for i in range(lo,len(self.instructions)):
            inst = self.instructions[i]
            print '%d\t%s\t%s' % (i,self.instLabels.get(i,''),"\t".join([str(ii) for ii in inst]))

##############################################################################
## The compiler
##############################################################################

class Compiler(object):
    """Compile prolog rules into a wam program."""

    def compileRules(self,rc,wamprog=None):
        if wamprog==None: wamprog = Program()
        for key in rc.index:
            for rule in rc.index[key]:
                rule.variabilize()
                wamprog.append(('comment',str(rule)))
                wamprog.insertLabel(key)
                self.compileRule(rule,wamprog)
        return wamprog

    def compileRule(self,rule,wamprog):
        # allocate variables
        nvars = rule.nvars
        if nvars>0:
            wamprog.append(('allocate',nvars,list(reversed(rule.variableList))))
        previousVars = set()
        # compile code to match the head
        if rule.lhs:
            for i,a in enumerate(rule.lhs.args):    
                relativeHeapIndex = -len(rule.lhs.args) + i
                if isProcessedConstant(a): 
                    wamprog.append(('unifyconst',a,relativeHeapIndex))
                elif a in previousVars:
                    wamprog.append(('unifyboundvar',a,relativeHeapIndex))
                else:
                    wamprog.append(('initfreevar',a,relativeHeapIndex))
                    previousVars.add(a)
            # now code to produce the features
            if rule.features==None:
                # if no features specified, create a unique 'id' feature for the rule
                ruleStartAddr = len(wamprog.instructions)
                rule.features = [Goal('id',[rule.lhs.functor,str(rule.lhs.arity),str(ruleStartAddr)])]
            #clear the feature stack
            wamprog.append(('fclear',))
            if rule.findall==None:
                #simple case - a list of features w/o a generator
                self.compileFeatures(rule,wamprog,previousVars)
            else:
                #complex case - a 'findall' generator for the
                #features. the code for the feature generation will be
                #inserted after the returnp, and inserted here will be
                #an opcode instructing the interpreter to execute that
                #code via depth-first search.
                placeToPatch = len(wamprog.instructions)
                wamprog.append(('ffindall',-1))
            #return the features
            wamprog.append(('freport',))
        # compile the body
        for g in rule.rhs:
            self.compileGoal(g,wamprog,previousVars)
        wamprog.append(('returnp',))
        # in the complex case, produce the code for feature generation
        # after the main body of the clause
        if rule.findall:
            wamprog.append(('comment',"features " + ",".join(map(str,rule.features)) + " : " + ",".join(map(str,rule.findall))))
            #patch the 'ffindall' opcode to point to the right place
            wamprog.instructions[placeToPatch] = ('ffindall',len(wamprog.instructions))
            #compile the generator code
            for g in rule.findall:
                self.compileGoal(g,wamprog,previousVars)                
            #compile the feature generation code
            self.compileFeatures(rule,wamprog,previousVars)
            wamprog.append(('returnp',))

    def compileFeatures(self,rule,wamprog,previousVars):
        for g in rule.features:
            wamprog.append(('fpushstart',g.functor,g.arity))
            for a in g.args:
                if isProcessedConstant(a): 
                    wamprog.append(('fpushconst',a))
                elif a in previousVars:
                    wamprog.append(('fpushboundvar',a))
                else:
                    assert False,'unbound variable in feature in rule: ' + str(rule)

    def compileGoal(self,g,wamprog,previousVars):
        for i,a in enumerate(g.args):
            if isProcessedConstant(a): 
                wamprog.append(('pushconst',a))
            elif a in previousVars:
                wamprog.append(('pushboundvar',a))
            else:
                wamprog.append(('pushfreevar',a))
                previousVars.add(a)
        wamprog.append(('callp','%s/%s' % (g.functor,g.arity)))



##############################################################################
## a test driver
##############################################################################

if __name__ == "__main__":

    def debug(argv):
        rules = RuleCollection()
        for ruleString in argv[1:]:
            #print ruleString,"==>",featureBlockNT.parseString(ruleString)
            ptree = ruleNT.parseString(ruleString)
            print ruleString,"==>",ptree
            if 'lhs' in ptree: print 'lhs:',ptree['lhs']
            if 'rhs' in ptree: print 'rhs',ptree['rhs']
            if 'features' in ptree: print 'features',ptree['features']
            r = Parser._convertRule(ptree)
            print 'rule:',r
            r.variabilize()
            print 'variabilized rule:',r
            rules.add(r)
        rules.listing()
        wp = Compiler().compileRules(rules)
        wp.listing()
    def listing(argv):
        rules = Parser.parseFile(argv[1])
        for f in argv[2:]:
            rules = Parser.parseFile(f,rules)

        #rules.listing()
        wp = Compiler().compileRules(rules)
        wp.listing()
    def serialize(argv):
        rules = Parser.parseFile(argv[1])
        for f in argv[2:]:
            rules = Parser.parseFile(f,rules)

        #rules.listing()
        wp = Compiler().compileRules(rules)
        wp.serialization()
    def help(argv):
        print "Options:\n\tdebug\n\tlist - print listing\n\tserialize - print serialization"
    if len(sys.argv)<=1: help(None)
    else:
        {
            'debug':debug,
            'list':listing,
            'serialize':serialize,
            'help':help
        }[sys.argv[1]](sys.argv[1:])
