#!/usr/bin/env python
#******************************************************************************
#  Name:     classify.py
#  Purpose:  supervised classification of multispectral images
#  Usage:             
#    python classify.py

import auxil.supervisedclass as sc
import auxil.readshp as rs
import gdal, os, time, sys, getopt
from osgeo.gdalconst import GA_ReadOnly, GDT_Byte
import matplotlib.pyplot as plt
import numpy as np
 
def main():    
    usage = '''
Usage: 
---------------------------------------------------------
python %s  [-p bandPositions] [- a algorithm] [-L number of hidden neurons (2D array)]   
[-P generate class probabilities image] [-n suppress graphics]  filename trainShapefile

bandPositions is a list, e.g., -p [1,2,4]  

algorithm  1=MaxLike
           2=NNet(backprop)
           3=NNet(congrad)
           4=Dnn(tensorflow)
           5=SVM

If the input file is named 

         path/filenbasename.ext then

The output classification file is named 

         path/filebasename_class.ext

the class probabilities output file is named

         path/filebasename_classprobs.ext
         
and the test results file is named

         path/filebasename_<classifier>.tst
--------------------------------------------------------''' %sys.argv[0]

    outbuffer = 50

    options, args = getopt.getopt(sys.argv[1:],'hnPp:a:L:')
    pos = None
    probs = False   
    L = 8
    trainalg = 1
    graphics = True
    for option, value in options:
        if option == '-h':
            print usage
            return
        elif option == '-p':
            pos = eval(value)
        elif option == '-n':
            graphics = False            
        elif option == '-a':
            trainalg = eval(value)
        elif option == '-L':
            L = eval(value)    
        elif option == '-P':
            probs = True                              
    if len(args) != 2: 
        print 'Incorrect number of arguments'
        print usage
        sys.exit(1)      
    if trainalg == 1:
        algorithm = 'MaxLike'
    elif trainalg == 2:
        algorithm = 'NNet(Backprop)'
    elif trainalg == 3:
        algorithm =  'NNet(Congrad)'
    elif trainalg == 4:
        algorithm =  'Dnn(tensorflow)'    
    else:
        algorithm = 'SVM'    
    print 'Training with %s'%algorithm          
    infile = args[0]  
    trnfile = args[1]      
    gdal.AllRegister() 
    if infile:                   
        inDataset = gdal.Open(infile,GA_ReadOnly)
        cols = inDataset.RasterXSize
        rows = inDataset.RasterYSize    
        bands = inDataset.RasterCount
        geotransform = inDataset.GetGeoTransform()
        if geotransform is not None:
            gt = list(geotransform) 
        else:
            print 'No geotransform available'
            return       
    else:
        return  
    if pos is None: 
        pos = range(1,bands+1)
    N = len(pos)    
    rasterBands = [] 
    for b in pos:
        rasterBands.append(inDataset.GetRasterBand(b))     
#  output files
    path = os.path.dirname(infile)
    basename = os.path.basename(infile)
    root, ext = os.path.splitext(basename)
    outfile = '%s/%s_class%s'%(path,root,ext)  
    tstfile = '%s/%s_%s.tst'%(path,root,algorithm)            
    if (trainalg in (2,3,4)) and probs:
#      class probabilities file
        probfile = '%s/%s_classprobs%s'%(path,root,ext) 
    else:
        probfile = None        
        
#  get the training data        
    Xs,Ls,K,classnames = rs.readshp(trnfile,inDataset,pos)       
    m = Ls.shape[0]
    
#  stretch the pixel vectors to [-1,1] for ffn, dnn
    maxx = np.max(Xs,0)
    minx = np.min(Xs,0)
    for j in range(len(pos)):
        Xs[:,j] = 2*(Xs[:,j]-minx[j])/(maxx[j]-minx[j]) - 1.0 
#  random permutation of training data
    idx = np.random.permutation(m)
    Xs = Xs[idx,:] 
    Ls = Ls[idx,:]     
#  train on 2/3 training examples         
    Xstrn = Xs[0:2*m//3,:]
    Lstrn = Ls[0:2*m//3,:] 
    Xstst = Xs[2*m//3:,:]  
    Lstst = Ls[2*m//3:,:]      
#  setup output datasets 
    driver = inDataset.GetDriver() 
    outDataset = driver.Create(outfile,cols,rows,1,GDT_Byte) 
    projection = inDataset.GetProjection()
    if geotransform is not None:
        outDataset.SetGeoTransform(tuple(gt))
    if projection is not None:
        outDataset.SetProjection(projection) 
    outBand = outDataset.GetRasterBand(1) 
    if probfile:   
        probDataset = driver.Create(probfile,cols,rows,K,GDT_Byte) 
        if geotransform is not None:
            probDataset.SetGeoTransform(tuple(gt))
        if projection is not None:
            probDataset.SetProjection(projection)  
        probBands = [] 
        for k in range(K):
            probBands.append(probDataset.GetRasterBand(k+1))         
#  initialize classifier  
    if   trainalg == 1:
        classifier = sc.Maxlike(Xstrn,Lstrn)
    elif trainalg == 2:
        classifier = sc.Ffnbp(Xstrn,Lstrn,L)
    elif trainalg == 3:
        classifier = sc.Ffncg(Xstrn,Lstrn,L)
    elif trainalg == 4:
        classifier = sc.Dnn(Xstrn,Lstrn,L) 
    elif trainalg == 5:
        classifier = sc.Svm(Xstrn,Lstrn)         
#  train it            
    print 'training on %i pixel vectors...' % np.shape(Xstrn)[0]
    print 'classes: %s'%str(classnames)
    start = time.time()
    result = classifier.train()
    print 'elapsed time %s' %str(time.time()-start) 
    if result is not None:
        if (trainalg in [2,3]) and graphics:
#          the cost array is returned in result, otherwise True            
            cost = np.log10(result)  
            ymax = np.max(cost)
            ymin = np.min(cost) 
            xmax = len(cost)      
            plt.plot(range(xmax),cost,'k')
            plt.axis([0,xmax,ymin-1,ymax])
            plt.title('Log(Cross entropy)')
            plt.xlabel('Epoch')              
#      classify the image           
        print 'classifying...'
        start = time.time()
        tile = np.zeros((outbuffer*cols,N),dtype=np.float32)    
        for row in range(rows/outbuffer):
            for j in range(N):
                tile[:,j] = rasterBands[j].ReadAsArray(0,row*outbuffer,cols,outbuffer).ravel()
                tile[:,j] = 2*(tile[:,j]-minx[j])/(maxx[j]-minx[j]) - 1.0               
            cls, Ms = classifier.classify(tile)  
            outBand.WriteArray(np.reshape(cls,(outbuffer,cols)),0,row*outbuffer)
            if probfile:
                Ms = np.byte(Ms*255)
                for k in range(K):
                    probBands[k].WriteArray(np.reshape(Ms[k,:],(outbuffer,cols)),0,row*outbuffer)
        outBand.FlushCache()
        print 'elapsed time %s' %str(time.time()-start)
        outDataset = None
        inDataset = None      
        if probfile:
            for probBand in probBands:
                probBand.FlushCache() 
            probDataset = None
            print 'class probabilities written to: %s'%probfile                       
        print 'thematic map written to: %s'%outfile
        if trainalg in [2,3]:
            plt.show()
        if tstfile:
            with open(tstfile,'w') as f:               
                print >>f, algorithm +'test results for %s'%infile
                print >>f, time.asctime()
                print >>f, 'Classification image: %s'%outfile
                print >>f, 'Class probabilities image: %s'%probfile
                print >>f, Lstst.shape[0],Lstst.shape[1]
                classes, _ = classifier.classify(Xstst)
                labels = np.argmax(Lstst,axis=1)+1
                for i in range(len(classes)):
                    print >>f, classes[i], labels[i]              
                f.close()
                print 'test results written to: %s'%tstfile
        print 'done'
    else:
        print 'an error occured' 
        return 
   
if __name__ == '__main__':
    main()