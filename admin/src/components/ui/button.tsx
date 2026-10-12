import * as React from 'react';
import {Slot} from '@radix-ui/react-slot';
import {cva,type VariantProps} from 'class-variance-authority';
import {LoaderCircle} from 'lucide-react';
import {cn} from '@/lib/utils';
const buttonVariants=cva('ui-button inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-all duration-200 active:scale-95 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',{variants:{variant:{default:'bg-primary text-primary-foreground',secondary:'bg-secondary text-secondary-foreground',outline:'border border-input bg-background',ghost:'hover:bg-accent hover:text-accent-foreground',destructive:'bg-destructive text-white'},size:{default:'h-10 px-4 py-2',sm:'h-8 px-3',icon:'size-10 p-0'}},defaultVariants:{variant:'default',size:'default'}});
interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>,VariantProps<typeof buttonVariants>{asChild?:boolean;isLoading?:boolean}
const Button=React.forwardRef<HTMLButtonElement,ButtonProps>(({className,variant,size,asChild=false,isLoading=false,disabled,children,type='button',...props},ref)=>{const Component=asChild?Slot:'button';return <Component ref={ref} type={type} className={cn(buttonVariants({variant,size}),className)} disabled={disabled||isLoading} aria-busy={isLoading||undefined} {...props}>{isLoading&&<LoaderCircle className="size-4 animate-spin" aria-hidden="true"/>}{children}</Component>});
Button.displayName='Button';export {Button,buttonVariants};
