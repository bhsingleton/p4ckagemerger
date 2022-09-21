# p4ckagemerger
A Python tool used to organize third party package updates into changelists for Perforce to submit.  

## How to use
To open the tool run the following command:  
```
from p4ckagemerger import qp4ckagemerger

window = qp4ckagemerger.QP4ckageMerger()
window.show()
```

The source directory represents the folder under source control whereas the target directory represents the folder with updates to be merged in.  

## Dependencies
At this time p4ckagemerger is dependent on the following packages: enum, dcc, and p4python.  
